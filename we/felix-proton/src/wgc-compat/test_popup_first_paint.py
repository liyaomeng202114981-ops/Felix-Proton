#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
# Copyright 2026 Felix Li, with OpenAI Codex assistance.
"""Run with xvfb-run on a disposable X server."""

import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

from Xlib import X, Xatom, display


SCRIPT = Path(__file__).with_name("popup_first_paint.py")
OPAQUE = 0xffffffff
WINDOW_CLASS = "FelixExitDialogTest"


class PopupFirstPaintTest(unittest.TestCase):
    def setUp(self):
        self.display = display.Display()
        self.addCleanup(self.display.close)
        screen = self.display.screen()
        self.root = screen.root
        argb = next(depth for depth in screen.allowed_depths if depth.depth == 32)
        self.visual = next(visual.visual_id for visual in argb.visuals
                           if visual.visual_class == X.TrueColor)
        self.colormap = self.root.create_colormap(self.visual, X.AllocNone)
        self.owner = self.root.create_window(
            0, 0, 800, 600, 0, screen.root_depth, X.InputOutput, X.CopyFromParent,
        )
        self.identify(self.owner, os.getpid())
        self.owner.map()
        self.display.sync()
        self.command = [sys.executable, "-B", str(SCRIPT), str(os.getpid()), hex(self.owner.id)]
        self.observer = subprocess.Popen(self.command, stdout=subprocess.DEVNULL)
        self.addCleanup(self.stop_observer)
        self.wait_for(lambda: self.root.get_attributes().all_event_masks & X.SubstructureNotifyMask)

    def stop_observer(self):
        if self.observer.poll() is None:
            self.observer.terminate()
        self.observer.wait(timeout=3)

    def wait_for(self, condition):
        deadline = time.monotonic() + 3
        while not condition():
            if time.monotonic() >= deadline:
                self.fail("Timed out waiting for the X11 window state")
            time.sleep(.005)

    def atom(self, name):
        return self.display.intern_atom(name)

    def identify(self, window, pid):
        window.set_wm_class(WINDOW_CLASS, WINDOW_CLASS)
        window.change_property(self.atom("_NET_WM_PID"), Xatom.CARDINAL, 32, [pid])

    def popup(self, pid, opacity=None):
        window = self.root.create_window(
            25, 25, 280, 162, 0, 32, X.InputOutput, self.visual,
            colormap=self.colormap, background_pixel=OPAQUE, border_pixel=0,
        )
        self.identify(window, pid)
        window.set_wm_transient_for(self.owner)
        window.change_property(self.atom("_NET_WM_STATE"), Xatom.ATOM, 32,
                               [self.atom("_NET_WM_STATE_SKIP_TASKBAR")])
        if opacity is not None:
            window.change_property(self.atom("_NET_WM_WINDOW_OPACITY"),
                                   Xatom.CARDINAL, 32, [opacity])
        window.map()
        self.display.sync()
        return window

    def opacity(self, window):
        value = window.get_full_property(self.atom("_NET_WM_WINDOW_OPACITY"), Xatom.CARDINAL)
        return None if value is None else value.value[0]

    def marker(self, window):
        return window.get_full_property(self.atom("_FELIX_EXIT_DIALOG_FIRST_PAINT"), Xatom.CARDINAL)

    def assert_released(self, window, opacity):
        self.assertEqual(self.opacity(window), opacity)
        self.assertIsNone(self.marker(window))

    def paint(self, window, color, area):
        gc = window.create_gc(foreground=color)
        window.fill_rectangle(gc, *area)
        gc.free()
        self.display.sync()

    def test_waits_for_body_and_button(self):
        unrelated = self.popup(self.observer.pid)
        matched = self.popup(os.getpid())
        self.wait_for(lambda: self.opacity(matched) == 0)
        self.assert_released(unrelated, None)
        self.paint(matched, 0xff252525, (0, 0, 280, 162))
        time.sleep(.06)
        self.assertEqual(self.opacity(matched), 0)
        self.paint(matched, 0xffe52650, (150, 110, 110, 33))
        self.wait_for(lambda: self.opacity(matched) is None and self.marker(matched) is None)

    def test_clean_stop_restores_opacity(self):
        matched = self.popup(os.getpid())
        self.wait_for(lambda: self.opacity(matched) == 0)
        self.stop_observer()
        self.assert_released(matched, None)

    def test_release_recovers_explicit_opacity(self):
        matched = self.popup(os.getpid(), OPAQUE)
        self.wait_for(lambda: self.opacity(matched) == 0)
        self.observer.kill()
        self.observer.wait(timeout=3)
        self.assertEqual(self.opacity(matched), 0)
        subprocess.run([*self.command, "--release"], check=True, timeout=3,
                       stdout=subprocess.DEVNULL)
        self.assert_released(matched, OPAQUE)


if __name__ == "__main__":
    unittest.main()
