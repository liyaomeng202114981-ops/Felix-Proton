# SPDX-License-Identifier: BSD-3-Clause
"""User-level desktop entry takeover. Callers retain their existing desktop IDs."""
import base64
from contextlib import contextmanager
import fcntl
from functools import wraps
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile


_VERSION = "0.1.0-test.1"
_TEST_IDS = tuple(f"felix-uu-{_VERSION}-{action}.desktop" for action in ("uu", "steam"))
_PREVIEW = "felix-uu-portal-preview1.desktop"
_MENU = ("steam.desktop", "uu-accelerator.desktop", "steam-uu.desktop", *_TEST_IDS, _PREVIEW)
_GROUP = "[Desktop Entry]"


class DesktopError(RuntimeError):
    pass


def _quote(value):
    value = str(value)
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise DesktopError("桌面启动路径含控制字符。")
    escaped = "".join("\\" + c if c in '\\"$`' else c for c in value)
    return '"' + escaped.replace("\\", "\\\\").replace("%", "%%") + '"'


def _groups(lines):
    group = ""
    for i, line in enumerate(lines):
        body = line.rstrip("\r\n")
        if body.startswith("[") and body.endswith("]"):
            group = body
        elif "=" in body and not body.startswith("#"):
            key, value = body.split("=", 1)
            yield i, group, key, value


def _lines(data, name):
    try:
        lines = data.decode("utf-8").splitlines(keepends=True)
    except UnicodeError as error:
        raise DesktopError(f"{name} 不是有效的 UTF-8 桌面条目。") from error
    if sum(line.rstrip("\r\n") == _GROUP for line in lines) != 1:
        raise DesktopError(f"{name} 缺少唯一的 Desktop Entry。")
    main = [(key, value) for _, group, key, value in _groups(lines) if group == _GROUP]
    if [value for key, value in main if key == "Type"] != ["Application"]:
        raise DesktopError(f"{name} 不是普通应用程序条目。")
    if any(key == "DBusActivatable" and value.strip().lower() == "true" for key, value in main):
        raise DesktopError(f"{name} 使用 D-Bus 激活，请先检查自定义入口。")
    return lines


def _steam_tail(value, home):
    commands = ("steam", "/usr/bin/steam", "/usr/games/steam", str(home / ".local/lib/uu-accelerator/steam"))
    for command in commands:
        for token in (command, _quote(command)):
            # A raw path containing whitespace is not one Exec argument.
            if token == command and any(c in " \t" for c in token):
                continue
            if value == token or value.startswith((token + " ", token + "\t")):
                return value[len(token):]
    raise DesktopError("Steam 启动命令不在已识别范围内，已保留原条目。")


def _rewrite(data, name, command, home, steam):
    lines = _lines(data, name)
    seen = set()
    for i, group, key, value in _groups(lines):
        if key != "Exec" or not (group == _GROUP or (steam and group.startswith("[Desktop Action "))):
            continue
        if group in seen:
            raise DesktopError(f"{name} 的同一分组存在重复 Exec。")
        seen.add(group)
        suffix = _steam_tail(value, home) if steam else ""
        newline = lines[i][len(lines[i].rstrip("\r\n")):]
        lines[i] = "Exec=" + command + suffix + newline
    if _GROUP not in seen:
        raise DesktopError(f"{name} 缺少主启动命令。")
    return "".join(lines).encode()


def _hide(data, name):
    lines = _lines(data, name)
    fields = [(i, val) for i, group, key, val in _groups(lines) if group == _GROUP and key == "NoDisplay"]
    if len(fields) > 1:
        raise DesktopError(f"{name} 的 NoDisplay 重复。")
    if fields:
        i, old = fields[0]
        ending = lines[i][len(lines[i].rstrip("\r\n")):]
        lines[i] = "NoDisplay=true" + ending
    else:
        i = next(i for i, line in enumerate(lines) if line.rstrip("\r\n") == _GROUP)
        ending = "\r\n" if lines[i].endswith("\r\n") else "\n"
        lines.insert(i + 1, "NoDisplay=true" + ending)
    return "".join(lines).encode()


def _verified_duplicate(name, path, data, home, xdg_data, xdg_config):
    if name == "steam-uu.desktop":
        expected = ("[Desktop Entry]\nType=Application\nName=Steam（UU 加速）\n"
                    "Comment=在网易 UU 的独立网络内启动 Steam\n"
                    f"Exec={home}/.local/lib/uu-accelerator/steam %U\nIcon=steam\n"
                    "Terminal=false\nCategories=Game;\nStartupWMClass=Steam\n")
        return data == expected.encode()
    if name in _TEST_IDS:
        action = "uu" if name == _TEST_IDS[0] else "steam"
        script = home / ".local/share/Steam/compatibilitytools.d" / ("felix-proton-uu-test-" + _VERSION) / "felix/local-beta.py"
        manifest = xdg_config / "felix-uu-test" / _VERSION / "owned-files.json"
    else:
        action = "open"
        script = xdg_data / "felix-uu-portal/preview1/start.py"
        manifest = xdg_config / "felix-uu-portal/preview1/owned-files.json"
    try:
        if manifest.is_symlink() or manifest.stat().st_uid != os.getuid():
            return False
        saved = json.loads(manifest.read_text(encoding="utf-8"))
        if saved.get("owner") != "Felix UU " + _VERSION:
            return False
        recorded = saved.get("files", {}).get(str(path))
        if recorded != hashlib.sha256(data).hexdigest():
            return False
        matches = [v for _, g, k, v in _groups(_lines(data, name)) if g == _GROUP and k == "Exec"]
        return matches == [f"/usr/bin/python3 {_quote(script)} {action}"]
    except (OSError, ValueError, AttributeError, DesktopError):
        return False


def _snapshot(path):
    if path.is_symlink():
        raise DesktopError(f"{path.name} 是符号链接，保留原文件。")
    try:
        with path.open("rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_size > 2 * 1024 * 1024:
                raise DesktopError(f"{path.name} 不属于当前用户、文件类型异常或体积过大。")
            data = stream.read()
            attrs = {key: base64.b64encode(os.getxattr(stream.fileno(), key)).decode("ascii")
                     for key in os.listxattr(stream.fileno()) if key.startswith("user.") or key == "system.posix_acl_access"}
    except FileNotFoundError:
        return None
    return {"data": base64.b64encode(data).decode("ascii"), "mode": stat.S_IMODE(info.st_mode), "gid": info.st_gid,
            "mtime": info.st_mtime_ns, "attrs": attrs}


def _content(snapshot):
    return base64.b64decode(snapshot["data"], validate=True)


def _changed(original, data):
    out = dict(original) if original is not None else {"mode": 0o644, "gid": os.getegid(), "attrs": {}}
    out.update(data=base64.b64encode(data).decode("ascii"), mtime=None)
    return out


def _same(left, right):
    if left is None or right is None:
        return left is right
    return all(left[key] == right[key] for key in ("data", "mode", "gid", "attrs"))


def _syncdir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic(path, data, mode=0o600, metadata=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".felix-desktop-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            if metadata and os.fstat(fd).st_gid != metadata["gid"]:
                os.fchown(fd, -1, metadata["gid"])
            os.fchmod(fd, mode)
            if metadata:
                for k, value in metadata["attrs"].items():
                    os.setxattr(fd, k, base64.b64decode(value, validate=True))
                if metadata["mtime"] is not None:
                    os.utime(fd, ns=(os.fstat(fd).st_atime_ns, metadata["mtime"]))
            os.fsync(fd)
        os.replace(tmp, path)
        _syncdir(path.parent)
    finally:
        Path(tmp).unlink(missing_ok=True)


@contextmanager
def _store(state_dir):
    private = Path(state_dir).expanduser().absolute() / "desktop-backup-v1"
    private.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = private.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise DesktopError("桌面备份目录必须由当前用户独占。")
    fd = os.open(private / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "r+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield private / "state.json"


def _locations(home, apps_dir, config_home):
    home = (Path(home) if home is not None else Path.home()).absolute()
    xdg_data = Path(os.environ.get("XDG_DATA_HOME") or home / ".local/share").absolute()
    apps = Path(apps_dir).absolute() if apps_dir is not None else xdg_data / "applications"
    config = Path(config_home or os.environ.get("XDG_CONFIG_HOME") or home / ".config").absolute()
    for directory in (apps, config / "autostart"):
        if directory.exists() and (not directory.is_dir() or directory.stat().st_uid != os.getuid()):
            raise DesktopError("目标不是当前用户自己的应用或自启目录。")
    targets = {name: apps / name for name in _MENU}
    targets["autostart/steam.desktop"] = config / "autostart/steam.desktop"
    return home, xdg_data, config, targets


def _plan(helper, paths, home, xdg_data, config, system_dirs):
    helper = Path(helper).expanduser().absolute()
    if not helper.is_file():
        raise DesktopError("找不到用于桌面入口的启动脚本。")
    prefix = "/usr/bin/python3 " + _quote(helper) + " "
    entries, skipped = {}, []
    for name, target in paths.items():
        duplicate = name in ("steam-uu.desktop", *_TEST_IDS, _PREVIEW)
        if target.is_symlink() and (duplicate or name == "autostart/steam.desktop"):
            skipped.append(name)
            continue
        before = _snapshot(target)
        if name in ("steam.desktop", "uu-accelerator.desktop"):
            system = next((Path(d) / name for d in system_dirs if (Path(d) / name).is_file()), None)
            if before:
                data = _content(before)
            elif system:
                data = system.read_bytes()
            elif name == "uu-accelerator.desktop":
                data = ("[Desktop Entry]\nType=Application\nName=网易 UU 加速器\nExec=uu\nIcon=network-vpn\n"
                        "Terminal=false\nCategories=Network;\nStartupWMClass=uu.exe\n").encode()
            else:
                raise DesktopError("未找到 steam.desktop，请先安装原生 Linux Steam。")
            steam = name == "steam.desktop"
            data = _rewrite(data, name, prefix + ("steam" if steam else "uu"), home, steam)
        elif before is None:
            continue
        elif name == "autostart/steam.desktop":
            try:
                data = _rewrite(_content(before), name, prefix + "steam", home, True)
            except DesktopError:
                skipped.append(name)
                continue
        else:
            data = _content(before)
            if not _verified_duplicate(name, target, data, home, xdg_data, config):
                skipped.append(name)
                continue
            data = _hide(data, name)
        after = _changed(before, data)
        if not _same(before, after):
            entries[name] = {"before": before, "after": after, "hidden": duplicate}
    return {"format": 1, "phase": "applying", "helper": str(helper), "paths": {k:str(v) for k,v in paths.items()},
            "files": entries, "skipped": skipped}


def _load(state_file, targets):
    if state_file.is_symlink():
        raise DesktopError("桌面备份记录是符号链接。")
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    if (not isinstance(state, dict) or state.get("format") != 1 or
            state.get("paths") != {k: str(v) for k,v in targets.items()} or
            not isinstance(state.get("files"), dict) or set(state["files"]) - set(targets)):
        raise DesktopError("备份记录与当前 XDG 目录不符，已停止操作。")
    return state


def _save(path, state):
    _atomic(path, (json.dumps(state, ensure_ascii=False, separators=(",", ":")) + "\n").encode())


def _apply_one(path, target):
    if target is None:
        path.unlink()
        _syncdir(path.parent)
    else:
        _atomic(path, _content(target), target["mode"], target)


def _replay(state, targets, direction, strict=False):
    changed = []
    other = "after" if direction == "before" else "before"
    def needed(name, entry):
        snapshot = _snapshot(targets[name])
        if _same(snapshot, entry[direction]):
            return False
        if strict or not _same(snapshot, entry[other]):
            raise DesktopError(f"{name} 已被其他程序或用户修改，保留当前文件。")
        return True
    for name, entry in state["files"].items():
        needed(name, entry)
    for name, entry in state["files"].items():
        if needed(name, entry):
            _apply_one(targets[name], entry[direction])
            changed.append(name)
    return changed


def _report_io_errors(function):
    @wraps(function)
    def call(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise DesktopError("桌面入口或备份无法读写；请检查权限、重试操作或从同一备份恢复。") from error
    return call


@_report_io_errors
def install(helper, state_dir, *, apps_dir=None, system_dirs=None, home=None, config_home=None):
    """Switch supported user entrypoints. system_dirs contains applications directories."""
    home, data, config, paths = _locations(home, apps_dir, config_home)
    if system_dirs is None:
        system_dirs = [Path(d) / "applications" for d in (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":") if d.startswith("/")]
    system_dirs = list(system_dirs)
    if paths["steam.desktop"].parent.resolve() in {Path(d).resolve() for d in system_dirs}:
        raise DesktopError("用户应用目录与系统应用目录相同，不能原地修改。")
    with _store(state_dir) as state_file:
        state = _load(state_file, paths)
        if state is None or state["phase"] == "restored":
            state = _plan(helper, paths, home, data, config, system_dirs)
            _save(state_file, state)
        if state["helper"] != str(Path(helper).expanduser().absolute()) or state["phase"] == "restoring":
            raise DesktopError("已有另一启动脚本或未完成的回退，请先恢复原入口。")
        changed = _replay(state, paths, "after", strict=state["phase"] == "installed")
        state["phase"] = "installed"
        _save(state_file, state)
        return {"changed": changed, "hidden": [n for n,e in state["files"].items() if e["hidden"]], "skipped": state["skipped"]}


@_report_io_errors
def restore(state_dir, *, apps_dir=None, home=None, config_home=None):
    """Restore original user files; drop overrides created from system desktop files."""
    _, _, _, paths = _locations(home, apps_dir, config_home)
    with _store(state_dir) as state_file:
        state = _load(state_file, paths)
        if state is None or state["phase"] == "restored":
            return {"changed": []}
        state["phase"] = "restoring"
        _save(state_file, state)
        changed = _replay(state, paths, "before")
        state["phase"] = "restored"
        _save(state_file, state)
        return {"changed": changed}
