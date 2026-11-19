#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
# Copyright 2026 Felix Li, with OpenAI Codex assistance.
"""Defer presentation of the companion's white exit dialog until it paints."""
import argparse
from contextlib import suppress
from dataclasses import dataclass
import os
import select
import signal
import time

from Xlib import X, Xatom, display, error

WIDTH, HEIGHT = 280, 162
OPAQUE = 0xffffffff
MAX_WAIT = 8.0
CHECK_INTERVAL = 0.008
SETTLE_SECONDS = 0.024


@dataclass
class HeldDialog:
    window: object
    previous: int | None
    started: float
    painted_since: float | None = None


class ExitDialogPresenter:
    def __init__(self, connection, parent_xid, pid):
        self.connection = connection
        self.root = connection.screen().root
        self.parent = connection.create_resource_object("window", parent_xid)
        self.pid = pid
        self.atoms = {name: connection.intern_atom(name) for name in (
            "_NET_WM_PID", "_NET_WM_WINDOW_OPACITY", "_NET_WM_STATE",
            "_NET_WM_STATE_SKIP_TASKBAR", "_FELIX_EXIT_DIALOG_FIRST_PAINT",
        )}
        if self.cardinal(self.parent, "_NET_WM_PID") != pid:
            raise ValueError("The owner window does not belong to this companion process")
        self.window_class = self.parent.get_wm_class()
        if not self.window_class:
            raise ValueError("The owner window has no WM_CLASS")
        self.held = {}
        self.pending = {}
        self.finished = set()

    def cardinal(self, window, name):
        prop = window.get_full_property(self.atoms[name], Xatom.CARDINAL)
        return int(prop.value[0]) if prop is not None and len(prop.value) == 1 else None

    def is_exit_dialog(self, window):
        geometry = window.get_geometry()
        if (geometry.width, geometry.height, geometry.depth) != (WIDTH, HEIGHT, 32):
            return False
        owner = window.get_wm_transient_for()
        if (owner is None or window.get_wm_class() != self.window_class
                or self.cardinal(window, "_NET_WM_PID") != self.pid
                or self.cardinal(owner, "_NET_WM_PID") != self.pid
                or owner.get_wm_class() != self.window_class):
            return False
        bounds = owner.get_geometry()
        if bounds.width < 700 or bounds.height < 400:
            return False
        state = window.get_full_property(self.atoms["_NET_WM_STATE"], Xatom.ATOM)
        return state is not None and self.atoms["_NET_WM_STATE_SKIP_TASKBAR"] in state.value

    @staticmethod
    def painted_frame(window):
        if window.get_attributes().map_state != X.IsViewable:
            return False
        # The buttons and labels are excluded by sampling the upper body.
        image = window.get_image(0, 0, WIDTH, 144, X.ZPixmap, OPAQUE).data
        dark = total = 0
        for y in range(10, 100, 8):
            for x in range(14, WIDTH - 14, 8):
                offset = (y * WIDTH + x) * 4
                blue, green, red, alpha = image[offset:offset + 4]
                total += 1
                if alpha >= 245 and max(red, green, blue) <= 85:
                    dark += 1
        if dark / total < .7:
            return False
        # The backing surface can briefly be dark while the controls are still
        # absent. Require the confirmation button as well as the actual body.
        button = 0
        for y in (118, 136):
            for x in (164, 184, 220, 240):
                offset = (y * WIDTH + x) * 4
                blue, green, red, alpha = image[offset:offset + 4]
                if alpha >= 245 and red >= 150 and red - max(green, blue) >= 65:
                    button += 1
        return button >= 6

    def hold(self, window, now):
        value = self.cardinal(window, "_NET_WM_WINDOW_OPACITY")
        if value not in (None, OPAQUE) or self.painted_frame(window):
            return
        window.change_property(self.atoms["_FELIX_EXIT_DIALOG_FIRST_PAINT"],
                               Xatom.CARDINAL, 32, [self.pid, value is not None])
        window.change_property(self.atoms["_NET_WM_WINDOW_OPACITY"], Xatom.CARDINAL, 32, [0])
        self.held[window.id] = HeldDialog(window, value, now)
        self.connection.flush()
        print(f"hold {window.id:#x}", flush=True)

    def reveal(self, dialog, reason):
        window = dialog.window
        owned, _ = self.lease(window)
        if owned:
            if self.cardinal(window, "_NET_WM_WINDOW_OPACITY") == 0:
                if dialog.previous is None:
                    window.delete_property(self.atoms["_NET_WM_WINDOW_OPACITY"])
                else:
                    window.change_property(self.atoms["_NET_WM_WINDOW_OPACITY"],
                                           Xatom.CARDINAL, 32, [dialog.previous])
            window.delete_property(self.atoms["_FELIX_EXIT_DIALOG_FIRST_PAINT"])
            self.connection.flush()
        waited = round((time.monotonic() - dialog.started) * 1000)
        print(f"release {window.id:#x} {reason} {waited}ms", flush=True)

    def lease(self, window):
        mark = window.get_full_property(self.atoms["_FELIX_EXIT_DIALOG_FIRST_PAINT"], Xatom.CARDINAL)
        owned = (mark is not None and len(mark.value) == 2 and mark.value[0] == self.pid
                 and self.cardinal(window, "_NET_WM_PID") == self.pid)
        return owned, OPAQUE if owned and mark.value[1] else None

    def recover(self):
        for window in self.root.query_tree().children:
            with suppress(error.XError):
                owned, previous = self.lease(window)
                if owned:
                    self.reveal(HeldDialog(window, previous, time.monotonic()), "recovered")

    def observe(self, stop, pidfd):
        self.root.change_attributes(event_mask=X.SubstructureNotifyMask)
        self.finished.update(window.id for window in self.root.query_tree().children)
        try:
            while not stop():
                readers, _, _ = select.select(
                    [pidfd, self.connection.fileno()], [], [],
                    CHECK_INTERVAL if self.held or self.pending else .25,
                )
                if pidfd in readers:
                    break
                now = time.monotonic()
                while self.connection.pending_events():
                    event = self.connection.next_event()
                    if event.type in (X.CreateNotify, X.MapNotify):
                        window = event.window
                        if window.id not in self.finished:
                            self.pending[window.id] = (window, now + .75)
                    elif event.type == X.DestroyNotify:
                        wid = event.window.id
                        self.finished.discard(wid)
                        self.pending.pop(wid, None)
                        self.held.pop(wid, None)
                for wid, (window, deadline) in tuple(self.pending.items()):
                    try:
                        matched = self.is_exit_dialog(window)
                        if matched:
                            self.hold(window, now)
                    except error.XError:
                        matched = False
                    if matched or now >= deadline:
                        self.pending.pop(wid, None)
                        if matched:
                            self.finished.add(wid)
                for wid, dialog in tuple(self.held.items()):
                    try:
                        if now - dialog.started >= MAX_WAIT:
                            self.reveal(dialog, "timeout")
                        else:
                            if not self.painted_frame(dialog.window):
                                dialog.painted_since = None
                            elif dialog.painted_since is None:
                                dialog.painted_since = now
                            elif now - dialog.painted_since >= SETTLE_SECONDS:
                                self.reveal(dialog, "painted")
                                self.held.pop(wid, None)
                            continue
                    except error.BadWindow:
                        pass
                    except error.XError:
                        dialog.painted_since = None
                        if now - dialog.started < MAX_WAIT:
                            continue
                    self.held.pop(wid, None)
        finally:
            for dialog in self.held.values():
                with suppress(error.XError):
                    self.reveal(dialog, "stop")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("owner_pid", type=int)
    parser.add_argument("parent_xid", type=lambda value: int(value, 0))
    parser.add_argument("--release", action="store_true", help="restore any interrupted presentation leases")
    args = parser.parse_args()
    stopped = False

    def stop(_signal, _frame):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        pidfd = os.pidfd_open(args.owner_pid)
    except ProcessLookupError:
        if args.release:
            return
        raise
    connection = display.Display()
    try:
        try:
            presenter = ExitDialogPresenter(connection, args.parent_xid, args.owner_pid)
        except (ValueError, error.BadWindow):
            if args.release:
                return
            raise
        presenter.recover()
        if not args.release:
            presenter.observe(lambda: stopped, pidfd)
    finally:
        connection.close()
        os.close(pidfd)


if __name__ == "__main__":
    main()
