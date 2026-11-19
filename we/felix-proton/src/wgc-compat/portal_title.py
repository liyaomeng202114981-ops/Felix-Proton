#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
# Copyright 2026 Felix Li, with OpenAI Codex assistance.
"""Read the selected row in this request's GNOME ScreenCast dialog."""
import unicodedata

import gi
from gi.repository import Gio, GLib

GNOME_PORTAL = "org.freedesktop.impl.portal.desktop.gnome"
SELECTION_EVENT = "object:state-changed:selected"
FALLBACK_TITLE = "Ubuntu 窗口"


def display_title(value):
    value = "".join(" " if unicodedata.category(c) in {"Cc", "Cf"} else c for c in value)
    # Keep the whole selection name within the Win32 UTF-16 title buffer.
    return " ".join(value.split()).encode("utf-16-le", "replace")[:480].decode(
        "utf-16-le", "ignore") or FALLBACK_TITLE


class SelectedWindowTitle:
    def __init__(self):
        self.title = FALLBACK_TITLE
        self.listener = None
        self.row = None
        self.dialog = None
        self.ambiguous = False
        self.timer = None

    @staticmethod
    def children(node):
        for index in range(min(node.get_child_count(), 100)):
            child = node.get_child_at_index(index)
            if child:
                yield child

    def visible_frames(self):
        return [frame for frame in self.children(self.app)
                if frame.get_state_set().contains(self.atspi.StateType.SHOWING)]

    def __enter__(self):
        try:
            gi.require_version("Atspi", "2.0")
            from gi.repository import Atspi

            self.atspi = Atspi
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            pid, = bus.call_sync(
                "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                "GetConnectionUnixProcessID", GLib.Variant("(s)", (GNOME_PORTAL,)),
                GLib.VariantType.new("(u)"), Gio.DBusCallFlags.NONE, 500, None,
            ).unpack()
            Atspi.init()
            Atspi.set_timeout(200, 500)
            self.app = next((app for app in self.children(Atspi.get_desktop(0))
                             if app.get_process_id() == pid), None)
            if self.app is not None and not self.visible_frames():
                listener = Atspi.EventListener.new(self.selected)
                if listener.register_with_app(SELECTION_EVENT, None, self.app):
                    self.listener = listener
                self.timer = GLib.timeout_add(220, self.poll)
        except (ImportError, ValueError, GLib.Error):
            pass
        return self

    def selected(self, event, *_):
        if self.ambiguous:
            return
        try:
            row = event.source
            if row.get_role() != self.atspi.Role.LIST_ITEM:
                return
            if not event.detail1:
                if row == self.row:
                    self.title = FALLBACK_TITLE
                    self.row = None
                return
            frames = self.visible_frames()
            if len(frames) != 1 or (self.dialog is not None and self.dialog != frames[0]):
                self.ambiguous = True
                self.title = FALLBACK_TITLE
                return
            frame = frames[0]
            if not frame.get_state_set().contains(self.atspi.StateType.MODAL):
                return
            parent = row.get_parent()
            for _ in range(24):
                if parent == frame:
                    self.dialog, self.row = frame, row
                    self.title = display_title(row.get_name() or "")
                    return
                if parent is None:
                    return
                parent = parent.get_parent()
        except GLib.Error:
            self.title = FALLBACK_TITLE

    def poll(self):
        try:
            frames = self.visible_frames()
            if len(frames) > 1:
                self.ambiguous = True
                self.title = FALLBACK_TITLE
            if self.ambiguous or not frames:
                return GLib.SOURCE_CONTINUE
            frame = frames[0]
            if not frame.get_state_set().contains(self.atspi.StateType.MODAL):
                return GLib.SOURCE_CONTINUE
            if self.dialog is not None and frame != self.dialog:
                self.ambiguous = True
                self.title = FALLBACK_TITLE
                return GLib.SOURCE_CONTINUE
            pending = [(frame, 0)]
            rows = []
            while pending:
                node, depth = pending.pop()
                if node.get_role() == self.atspi.Role.LIST_ITEM:
                    if node.get_state_set().contains(self.atspi.StateType.SELECTED):
                        rows.append(node)
                elif depth < 18:
                    pending.extend((child, depth + 1) for child in self.children(node))
            if len(rows) == 1:
                self.dialog, self.row = frame, rows[0]
                self.title = display_title(self.row.get_name() or "")
            else:
                self.row = None
                self.title = FALLBACK_TITLE
        except GLib.Error:
            pass
        return GLib.SOURCE_CONTINUE

    def __exit__(self, *_):
        if self.timer is not None:
            GLib.source_remove(self.timer)
        if self.listener is not None:
            try:
                self.listener.deregister(SELECTION_EVENT)
            except GLib.Error:
                pass
