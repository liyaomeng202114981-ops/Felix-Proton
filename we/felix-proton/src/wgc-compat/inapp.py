#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
# Copyright 2026 Felix Li, with OpenAI Codex assistance.
"""Authorize monitor or window capture inside one running companion session."""
import argparse
import json
import os
from pathlib import Path
import re
import select
import signal
import stat
import subprocess
import sys
import time
from dataclasses import dataclass

from douyin_native import runtime_dir

MODES = ("window", "monitor")


@dataclass
class Share:
    mode: str
    directory: Path
    child: subprocess.Popen
    token: str | None
    frame_deadline: float | None = None
    stopped: bool = False
    handle: int | None = None
    material_seen: bool = False
    missing_since: float | None = None

    def cancel(self):
        if not self.stopped:
            self.stopped = True
            self.child.terminate()

    def ready(self, runtime):
        if not (self.directory / "frames.sock").is_socket():
            return False
        if self.mode == "monitor":
            return True
        try:
            width, height = map(int, (self.directory / "source-size").read_text().split())
            limit = 4096 if self.token else 8192
            if not (1 <= width <= limit and 1 <= height <= limit):
                raise ValueError
        except (OSError, ValueError):
            if self.token:
                if self.frame_deadline is None:
                    self.frame_deadline = time.monotonic() + 12
                elif time.monotonic() >= self.frame_deadline:
                    print("Window stream delivered no valid frame before the deadline", flush=True)
                    self.cancel()
            return False
        answer = self.directory / "ready" if self.token else runtime / "window-ready"
        write_atomic(answer, f"{width} {height}\n")
        return True

    def check_material(self, windows):
        if not self.token or self.stopped:
            return
        if self.handle is None:
            try:
                self.handle = int((self.directory / "material").read_text())
            except (OSError, ValueError):
                return
        if self.handle in windows:
            self.material_seen = True
            self.missing_since = None
        elif self.material_seen:
            now = time.monotonic()
            if self.missing_since is None:
                self.missing_since = now
            elif now - self.missing_since > 1.0:
                self.cancel()

    def closed(self, runtime, was_pending):
        if self.token:
            for name in ("ready", "cancel", "frames.sock", "companion.pid", "deliver",
                         "source-size", "first-lease", "source-title", "material"):
                (self.directory / name).unlink(missing_ok=True)
            write_atomic(self.directory / "closed", "closed\n")
        elif was_pending and self.mode == "window":
            write_atomic(runtime / "window-cancelled", "closed\n")


def start_share(runtime, payload, request, identity, parent):
    mode, token = request
    directory = runtime / mode
    if token:
        directory = request_directory(runtime, token)
        # The fresh request directory is reserved by the helper before publishing.
        if directory is None:
            return None
        if (directory / "cancel").exists():
            (directory / "cancel").unlink(missing_ok=True)
            write_atomic(directory / "closed", "closed\n")
            return None
    directory = runtime_dir(directory)
    directory.mkdir(mode=0o700, exist_ok=True)
    for name in ("deliver", "source-size", "first-lease", "source-title"):
        (directory / name).unlink(missing_ok=True)
    write_atomic(directory / "companion.pid", identity)
    if mode == "window" and not token:
        (runtime / "window-ready").unlink(missing_ok=True)
        (runtime / "window-cancelled").unlink(missing_ok=True)
    child = subprocess.Popen([
        sys.executable, "-B", str(Path(__file__).with_name("douyin_native.py")),
        mode, str(payload), "--directory", str(directory), "--running-owner",
        "--parent-window", parent,
    ])
    print(f"requested {mode}" + (f" {token}" if token else ""), flush=True)
    return Share(mode, directory, child, token)


def read_request(value):
    if value in MODES:
        return value, None
    match = re.fullmatch(r"window ([1-9][0-9]{0,9})", value)
    if match and 3 <= int(match[1]) <= 0xffffffff:
        return "window", match[1]
    return None


def request_directory(runtime, token):
    root = runtime / "window"
    directory = root / token
    for path in (root, directory):
        try:
            info = path.lstat()
        except FileNotFoundError:
            return None
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            return None
        # Wine creates both directories beneath the already private runtime
        # with the Wine process's umask.
        path.chmod(0o700)
    return directory


class MonitorMaterials:
    def __init__(self, path):
        self.path = path
        self.revision = None
        self.known = None
        self.windows = set()
        self.added()

    def added(self):
        if self.path is None:
            return False
        try:
            revision = self.path.stat().st_mtime_ns
            if revision == self.revision:
                return False
            store = json.loads(self.path.read_text())["sourceStore"]
            scenes = store["sceneSource"]
            current = store["currentScene"]
        except (OSError, ValueError, KeyError, TypeError):
            return False

        if not isinstance(scenes, dict):
            return False

        windows = set()
        seen = {}
        for scene_id, scene in scenes.items():
            if not isinstance(scene, dict):
                continue
            seen[scene_id] = 0
            for key in ("data", "data2"):
                rows = scene.get(key)
                if not isinstance(rows, dict):
                    continue
                for item in rows.values():
                    if not isinstance(item, dict):
                        continue
                    if item.get("type") == "monitor":
                        seen[scene_id] += 1
                    payload = item.get("payload")
                    if (item.get("type") == "window" and isinstance(payload, dict)
                            and payload.get("windowClass") == "FelixWgcFixtureWindow"
                            and isinstance(payload.get("handle"), int)):
                        windows.add(payload["handle"])
        # The companion regenerates source IDs when it restores saved scenes.
        # A relabelled source must not open the chooser during normal startup.
        added = self.known is not None and seen.get(current, 0) > self.known.get(current, 0)
        self.known = seen
        self.windows = windows
        self.revision = revision
        return added


def write_atomic(path, text):
    pending = path.with_suffix(".new")
    pending.write_text(text, encoding="ascii")
    pending.replace(path)


def companion_parent(xid, pid):
    if xid is None:
        return ""
    from Xlib import X, display

    connection = display.Display()
    try:
        window = connection.create_resource_object("window", xid)
        prop = window.get_full_property(connection.intern_atom("_NET_WM_PID"), X.AnyPropertyType)
        if prop is None or int(prop.value[0]) != pid:
            raise ValueError("The Portal parent does not belong to the companion")
        return f"x11:{xid:x}"
    finally:
        connection.close()


def capture_requests(runtime, payload, owner_pid, source_store, xid):
    os.umask(0o077)
    parent = companion_parent(xid, owner_pid)
    owner_start = Path(f"/proc/{owner_pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    owner = os.pidfd_open(owner_pid)
    try:
        poll = select.poll()
        poll.register(owner, select.POLLIN)
        run_requests(runtime_dir(runtime), payload, f"{owner_pid} {owner_start}\n", poll,
                     MonitorMaterials(source_store), parent)
    finally:
        os.close(owner)


def run_requests(runtime, payload, owner_identity, owner, monitors, parent):
    children = {}
    pending = None
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    request = runtime / "request"
    try:
        while not stopping and not owner.poll(0):
            choice = ("monitor", None) if monitors.added() else None
            for key, share in tuple(children.items()):
                if share.child.poll() is not None:
                    children.pop(key)
                    share.closed(runtime, pending == key)
                    if pending == key:
                        pending = None
                    print(f"closed {share.mode} {share.token or ''} exit={share.child.returncode}", flush=True)
                elif share.token and (share.directory / "cancel").exists():
                    share.cancel()
                elif pending == key and not share.stopped and share.ready(runtime):
                    pending = None
                    print(f"authorized {share.mode}" + (f" {share.token}" if share.token else ""), flush=True)
                else:
                    share.check_material(monitors.windows)
            if request.is_file():
                choice = read_request(request.read_text(encoding="ascii").strip())
                request.unlink()
            if choice and choice not in children:
                if pending is None:
                    share = start_share(runtime, payload, choice, owner_identity, parent)
                    if share is not None:
                        children[choice] = share
                        pending = choice
                elif choice[1]:
                    # A token must always receive a response, even if another
                    # OS picker is already open.
                    directory = request_directory(runtime, choice[1])
                    if directory is not None:
                        write_atomic(directory / "closed", "busy\n")
            time.sleep(.1)
    finally:
        for share in children.values():
            if share.child.poll() is None:
                share.cancel()
        for key, share in children.items():
            child = share.child
            try:
                child.wait(timeout=6)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
            share.closed(runtime, pending == key)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runtime", type=Path)
    parser.add_argument("payload", type=Path)
    parser.add_argument("owner_pid", type=int)
    parser.add_argument("--source-store", type=Path)
    parser.add_argument("--parent-xid", type=lambda value: int(value, 0))
    args = parser.parse_args()
    capture_requests(args.runtime, args.payload, args.owner_pid, args.source_store, args.parent_xid)
