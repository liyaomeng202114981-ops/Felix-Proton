#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
# Copyright 2026 Felix Li, with OpenAI Codex assistance.
"""Keep one Portal authorization alive for a single Companion launch."""
import argparse
from contextlib import suppress
import os
from pathlib import Path
import select
import signal
import stat
import subprocess
import sys
import time

from gi.repository import GLib, GLibUnix
from portal_title import SelectedWindowTitle

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "wayland-capture"))
from portal import MonitorSession, WindowSession

LAYERS = "VK_LAYER_FELIX_wgc_dmabuf"
WINDOW_TITLE = "Felix Wayland Window"
UNIT = "felix-douyin-wgc.service"
WINDOW_UNIT = "felix-douyin-wgc-window.service"
INAPP_DIRECTORY = "felix-douyin-inapp"


def runtime_dir(directory=None):
    if directory is None:
        directory = Path(os.environ["XDG_RUNTIME_DIR"]) / "felix-douyin-wgc"
    if directory.exists():
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise RuntimeError("屏幕共享目录的所有者或权限不正确。")
    return directory


def render_node():
    nodes = list(Path("/dev/dri").glob("renderD*"))
    if len(nodes) != 1:
        raise RuntimeError("当前采集实现需要一个可确定的 GPU render node。")
    return nodes[0]


def app_environment(mode, payload, runtime):
    layer_dir = payload / "vulkan"
    library = str(layer_dir / "libfelixwgc.so")
    env = {
        "FELIX_WGC_GPU_UNIXLIB": "\\??\\Z:" + library.replace("/", "\\"),
        "FELIX_WGC_GPU_RENDER_NODE": str(render_node()),
        "FELIX_WGC_FIXTURE_TITLE": WINDOW_TITLE,
        "FELIX_WGC_FRAME_RATE": "30",
        "VK_ADD_LAYER_PATH": str(layer_dir),
        "VK_INSTANCE_LAYERS": LAYERS,
        "PRESSURE_VESSEL_FILESYSTEMS_RW": str(runtime),
        "WINEDLLOVERRIDES": "d3d11=n;graphicscapture=n",
    }

    if mode == "in-app":
        env["FELIX_WGC_AUTO_DIR"] = str(runtime)
    else:
        env["FELIX_WGC_GPU_SOURCE"] = mode
        env["FELIX_WGC_GPU_SOCKET"] = str(runtime / "frames.sock")
    return env


def open_owner(directory):
    pid, start = (directory / "companion.pid").read_text().split()
    try:
        if Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19] == start:
            return os.pidfd_open(int(pid))
    except (FileNotFoundError, ProcessLookupError):
        pass
    return None


def relay(mode, payload, directory=None, *, running_owner=False, parent_window=""):
    directory = runtime_dir(directory)
    wait_seconds = 240 if running_owner else 150
    session = MonitorSession(wait_seconds) if mode == "monitor" else WindowSession(wait_seconds)
    child = None
    owner = None
    title_path = directory / "source-title"
    # The running in-app owner is already settled. Keep its initial frame,
    # including when the selected window is idle and sends no updates.
    immediate = running_owner and mode == "window" and directory.name.isdecimal()
    titled_window = mode == "window" and running_owner and os.environ.get("FELIX_WGC_DYNAMIC_TITLE") == "1"
    try:
        if titled_window:
            with SelectedWindowTitle() as selection:
                node, fd = session.select("直播伴侣", parent_window)
        else:
            node, fd = session.select("直播伴侣", parent_window)
        worker = payload / "window-stream"
        sync_worker = payload / "window-stream-explicit-sync"
        interactive_worker = payload / "window-stream-interactive"
        if mode == "window" and sync_worker.is_file():
            worker = sync_worker
        if immediate and interactive_worker.is_file():
            worker = interactive_worker
        arguments = [str(worker), str(render_node()), str(fd), str(node),
                     str(directory / "frames.sock")]
        if mode == "monitor":
            arguments.append("--monitor")
        try:
            if titled_window:
                with suppress(OSError):
                    title_path.write_text(selection.title + "\n", encoding="utf-8")
            deliver = directory / "deliver"
            if immediate:
                owner = open_owner(directory)
                if owner is None:
                    return
                deliver.touch(mode=0o600)
            worker_env = os.environ | {"FELIX_WGC_START_GATE": str(deliver)}
            if worker == interactive_worker:
                worker_env["FELIX_WGC_RETAIN_FIRST"] = "1"
            if running_owner and mode == "window":
                worker_env["FELIX_WGC_SIZE_FILE"] = str(directory / "source-size")
                worker_env["FELIX_WGC_FIRST_LEASE_FILE"] = str(directory / "first-lease")
            child = subprocess.Popen(
                arguments, pass_fds=(fd,), env=worker_env,
            )
        finally:
            os.close(fd)

        loop = GLib.MainLoop()
        deadline = time.monotonic() + 90
        deliver_at = None
        started = immediate
        def check_live():
            nonlocal owner, deliver_at, started
            if owner is None:
                try:
                    owner = open_owner(directory)
                except FileNotFoundError:
                    pass
                else:
                    if owner is None:
                        loop.quit()
                        return GLib.SOURCE_REMOVE
                    # The companion replaces its first Media SDK process at
                    # startup on this Proton build. Do not lease a DMA-BUF
                    # to an SDK instance that is about to exit.
                    deliver_at = time.monotonic() + (0 if running_owner else 10)
            if owner is not None:
                ready = select.poll()
                ready.register(owner, select.POLLIN)
                expired = bool(ready.poll(0))
            else:
                expired = time.monotonic() >= deadline
            if session.closed_by_portal or child.poll() is not None or expired:
                loop.quit()
                return GLib.SOURCE_REMOVE
            if not started and deliver_at is not None and time.monotonic() >= deliver_at:
                deliver.touch(mode=0o600)
                started = True
            return GLib.SOURCE_CONTINUE

        GLib.timeout_add(200, check_live)
        def terminate():
            loop.quit()
            return GLib.SOURCE_REMOVE
        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, terminate)
        loop.run()
    finally:
        if titled_window:
            with suppress(OSError):
                title_path.unlink(missing_ok=True)
        if owner is not None:
            os.close(owner)
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=4)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("monitor", "window"))
    parser.add_argument("payload", type=Path)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--running-owner", action="store_true")
    parser.add_argument("--parent-window", default="")
    args = parser.parse_args()
    relay(args.mode, args.payload, args.directory, running_owner=args.running_owner,
          parent_window=args.parent_window)
