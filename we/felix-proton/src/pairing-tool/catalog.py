# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Felix Li, with OpenAI Codex assistance.
"""Read installed application metadata; never evaluate or execute a desktop file."""
from dataclasses import dataclass
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


_SUPPORTED = {
    "steam.desktop": "platform",
    "uu-accelerator.desktop": "accelerator",
}
_DESKTOP_ID = re.compile(r"[A-Za-z0-9_.-]+\.desktop")


@dataclass(frozen=True)
class App:
    desktop_id: str
    name: str
    icon: object
    filename: str
    kind: str
    supported: bool = True


def classify(desktop_id, executable=None):
    """The first adapter supports exact IDs, including already-integrated entries.

    A display name or an executable named 'steam' is not sufficient to qualify
    another desktop ID. Executable is accepted for metadata callers but unused.
    """
    return _SUPPORTED.get(desktop_id)


def _inventory():
    import gi
    gi.require_version("Gio", "2.0")
    try:
        gi.require_version("GioUnix", "2.0")
        from gi.repository import GioUnix
        # Importing this namespace installs the DesktopAppInfo override on new
        # GLib versions. We only read AppInfo methods; no application is launched.
        _ = GioUnix.DesktopAppInfo
    except (ImportError, ValueError):
        pass
    from gi.repository import Gio
    return Gio.AppInfo.get_all()


def load_apps():
    """Return the effective installed Steam and UU entries with original icons."""
    apps = {}
    for info in _inventory():
        try:
            desktop_id = info.get_id()
            kind = classify(desktop_id)
            if kind is None or desktop_id in apps or not info.should_show():
                continue
            filename = info.get_filename()
            if not filename or not Path(filename).is_absolute():
                continue
            path = Path(filename).resolve(strict=True)
            if not path.is_file():
                continue
            apps[desktop_id] = App(desktop_id, info.get_display_name(), info.get_icon(),
                                   str(path), kind)
        except (OSError, RuntimeError, ValueError, AttributeError):
            # A removed desktop entry cannot be imported as an arbitrary file.
            continue
    return sorted(apps.values(), key=lambda app: (app.kind != "platform", app.name.casefold()))


def _installed(desktop_id, apps):
    if not _DESKTOP_ID.fullmatch(desktop_id) or desktop_id not in _SUPPORTED:
        raise ValueError("首版只支持 Steam 和网易 UU 的应用图标。")
    for app in apps:
        if app.desktop_id == desktop_id:
            return app
    raise ValueError("未找到这个已安装的应用，请先安装 Steam 和网易 UU。")


def resolve_drop(value):
    """Resolve one internal ID or local desktop URI against the effective catalog.

    File-manager drops must refer to the installed entry itself. Arbitrary
    desktop files, even with a matching filename/name, are never imported.
    """
    if not isinstance(value, str):
        raise ValueError("请拖入一个应用图标。")
    value = value.strip()
    if not value or any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("请一次拖入一个应用图标。")
    apps = load_apps()
    if value.startswith("felix-app:"):
        return _installed(value[len("felix-app:"):], apps)
    if value.startswith("application://"):
        desktop_id = value[len("application://"):]
        # The GNOME application URI carries an ID, not a remote host/path.
        return _installed(desktop_id, apps)
    if value.startswith("file:"):
        uri = urlsplit(value)
        if (uri.scheme != "file" or uri.netloc not in ("", "localhost")
                or uri.query or uri.fragment):
            raise ValueError("只支持本机已安装的应用图标。")
        try:
            candidate = Path(unquote(uri.path, encoding="utf-8", errors="strict"))
        except UnicodeError:
            raise ValueError("应用图标路径无效。") from None
    else:
        candidate = Path(value)
    if (not candidate.is_absolute() or candidate.suffix != ".desktop"
            or any(ord(character) < 32 or ord(character) == 127 for character in str(candidate))):
        raise ValueError("请拖入 Steam 或网易 UU 的已安装应用图标。")
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        raise ValueError("找不到这个应用图标。") from None
    for app in apps:
        if resolved == Path(app.filename):
            return app
    raise ValueError("这个文件不是当前已安装的 Steam 或网易 UU 入口。")
