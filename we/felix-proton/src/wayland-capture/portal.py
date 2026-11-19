# SPDX-License-Identifier: BSD-3-Clause
# Copyright 2026 Felix Li, with OpenAI Codex assistance.
"""One explicitly authorized XDG ScreenCast source on a private PipeWire remote."""

import secrets

from gi.repository import Gio, GLib

DEST = "org.freedesktop.portal.Desktop"
ROOT = "/org/freedesktop/portal/desktop"
CAST = "org.freedesktop.portal.ScreenCast"
REQUEST = "org.freedesktop.portal.Request"
SESSION = "org.freedesktop.portal.Session"
MONITOR, WINDOW = 1, 2
REQUEST_SIGNATURES = {"CreateSession": "(a{sv})", "SelectSources": "(oa{sv})", "Start": "(osa{sv})"}


class CaptureError(RuntimeError):
    pass


class ScreenCastSession:
    source_type = None
    source_name = ""
    def __init__(self, wait_seconds):
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        self.wait_seconds = wait_seconds
        self.handle = None
        self.subscription = None
        self.closed_by_portal = False
        self.close_acknowledged = False
        self.properties = {}

    def call(self, path, interface, method, signature="()", args=()):
        return self.bus.call_sync(
            DEST, path, interface, method, GLib.Variant(signature, args),
            None, Gio.DBusCallFlags.NONE, 5000,
        ).unpack()

    def request(self, method, session_args, options, wait_seconds=5):
        token = "felix_" + secrets.token_hex(12)
        sender = self.bus.get_unique_name()[1:].replace(".", "_")
        expected = f"{ROOT}/request/{sender}/{token}"
        options = {**options, "handle_token": GLib.Variant("s", token)}
        loop = GLib.MainLoop()
        reply = []
        timeout_id = None
        handle = None

        def response(_bus, _sender, _path, _iface, _signal, values):
            reply.append(values.unpack())
            loop.quit()

        def timed_out():
            nonlocal timeout_id
            timeout_id = None
            loop.quit()
            return GLib.SOURCE_REMOVE

        subscription = self.bus.signal_subscribe(
            DEST, REQUEST, "Response", expected, None, Gio.DBusSignalFlags.NONE, response,
        )
        try:
            signature = REQUEST_SIGNATURES[method]
            handle, = self.call(ROOT, CAST, method, signature, (*session_args, options))
            if handle != expected:
                raise CaptureError(f"{method} returned an unexpected request path")
            if not reply:
                timeout_id = GLib.timeout_add_seconds(wait_seconds, timed_out)
                loop.run()
            if not reply:
                raise CaptureError(f"{method} timed out")
            code, data = reply[0]
            if code:
                raise CaptureError(f"{method} ended with portal response {code}")
            return data
        finally:
            if timeout_id is not None:
                GLib.source_remove(timeout_id)
            self.bus.signal_unsubscribe(subscription)
            if handle and not reply:
                try:
                    self.call(handle, REQUEST, "Close")
                except GLib.Error:
                    pass

    def select(self, title, parent_window=""):
        options = {"session_handle_token": GLib.Variant("s", "felix_" + secrets.token_hex(12))}
        self.handle = self.request("CreateSession", (), options)["session_handle"]
        self.subscription = self.bus.signal_subscribe(
            DEST, SESSION, "Closed", self.handle, None, Gio.DBusSignalFlags.NONE,
            self.on_closed,
        )
        self.request("SelectSources", (self.handle,), {
            "types": GLib.Variant("u", self.source_type),
            "multiple": GLib.Variant("b", False),
        })
        print(f"SELECT {self.source_name}: {title}", flush=True)
        streams = self.request("Start", (self.handle, parent_window), {}, self.wait_seconds).get("streams", [])
        if len(streams) != 1:
            raise CaptureError(f"Expected one authorized source, received {len(streams)} streams")
        node, properties = streams[0]
        if properties.get("source_type", self.source_type) != self.source_type:
            raise CaptureError(f"Portal returned a different source type for {self.source_name}")
        self.properties = properties
        return node, self.open_remote()

    def open_remote(self):
        if not self.handle or self.closed_by_portal:
            raise CaptureError("The authorized capture session has ended")
        reply, fds = self.bus.call_with_unix_fd_list_sync(
            DEST, ROOT, CAST, "OpenPipeWireRemote", GLib.Variant("(oa{sv})", (self.handle, {})),
            GLib.VariantType.new("(h)"), Gio.DBusCallFlags.NONE, 5000, None, None,
        )
        return fds.get(reply.unpack()[0])

    def on_closed(self, *_args):
        self.closed_by_portal = True

    def close(self):
        try:
            if self.handle and not self.closed_by_portal:
                try:
                    self.call(self.handle, SESSION, "Close")
                    self.close_acknowledged = True
                except GLib.Error as error:
                    # Some backends remove a cancelled session before the client sees Closed.
                    if Gio.DBusError.get_remote_error(error) not in {
                        "org.freedesktop.DBus.Error.UnknownObject",
                        "org.freedesktop.DBus.Error.UnknownMethod",
                    }:
                        raise
                    self.closed_by_portal = True
        finally:
            if self.subscription is not None:
                self.bus.signal_unsubscribe(self.subscription)
                self.subscription = None
            self.handle = None


class WindowSession(ScreenCastSession):
    source_type = WINDOW
    source_name = "WINDOW"


class MonitorSession(ScreenCastSession):
    source_type = MONITOR
    source_name = "MONITOR"
