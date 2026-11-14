# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Felix Li, with OpenAI Codex assistance.
"""One reversible Steam/UU desktop pairing, without starting either application.

The existing native-ux helper still owns all runtime/network behavior. This module
only checks that installed integration and changes the two selected desktop Exec
values. Its separate journal never calls the legacy multi-entry installer/restore.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat


PLATFORM_ID = "steam.desktop"
ACCELERATOR_ID = "uu-accelerator.desktop"
IDS = (PLATFORM_ID, ACCELERATOR_ID)
CONNECTION_KEYS = ("prefix", "runner", "wrapper", "steam_real", "uu_executable",
                   "pasta_bin_dir", "desktop_wrapper")


class PairingError(RuntimeError):
    pass


class PairingService:
    def __init__(self, *, home=None, config_home=None, data_home=None, state_home=None,
                 helper=None, system_dirs=None, native_dir=None):
        supplied_home = home is not None
        self.home = Path(home or Path.home()).expanduser().absolute()
        def base(explicit, variable, fallback):
            value = explicit or (None if supplied_home else os.environ.get(variable))
            path = Path(value or self.home / fallback).expanduser()
            if not path.is_absolute():
                raise PairingError("应用目录必须是绝对路径。")
            return path
        self.config_home = base(config_home, "XDG_CONFIG_HOME", ".config")
        self.data_home = base(data_home, "XDG_DATA_HOME", ".local/share")
        self.state_home = base(state_home, "XDG_STATE_HOME", ".local/state")
        self.apps = self.data_home / "applications"
        self.helper = Path(helper or self.data_home / "felix-native-ux/v1/routes.py").absolute()
        self.active = self.config_home / "felix-native-ux/active.json"
        self.private = self.state_home / "felix-pairing-tool/v1"
        self.ledger = self.private / "pair.json"
        if system_dirs is None:
            system_dirs = [Path(d) / "applications" for d in
                           os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":")
                           if d.startswith("/")]
        self.system_dirs = tuple(Path(d).absolute() for d in system_dirs)
        source_native = Path(__file__).resolve().parent.parent / "native-ux"
        bundled_native = Path(__file__).resolve().parent / "lib"
        native = Path(native_dir) if native_dir is not None else (
            bundled_native if (bundled_native / "desktop.py").is_file() else
            source_native if (source_native / "desktop.py").is_file() else self.helper.parent)
        module_path = native / "desktop.py"
        if not module_path.is_file():
            raise PairingError("未找到已有桌面入口组件，请先准备 Felix-Proton 集成。")
        spec = importlib.util.spec_from_file_location("felix_pairing_desktop", module_path)
        self.desktop = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.desktop)

    def _json(self, path, *, private=False):
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_size > 2 * 1024 * 1024 or private and info.st_mode & 0o077):
            raise PairingError("配置或配对记录的归属、类型或权限异常，已保留原文件。")
        return json.loads(path.read_text(encoding="utf-8"))

    def _prerequisites(self):
        active = self._json(self.active, private=True)
        if (not isinstance(active, dict) or set(active) != {"config"}
                or not isinstance(active["config"], str) or not Path(active["config"]).is_absolute()):
            raise PairingError("已有网络配置指针无效，请先完成 Felix-Proton 的 Steam/UU 设置。")
        config_path = Path(active["config"])
        config = self._json(config_path, private=True)
        required = {"prefix", "runner", "wrapper", "steam_real", "uu_executable"}
        if not isinstance(config, dict) or not required <= config.keys():
            raise PairingError("已有 Steam/UU 网络配置不完整。")
        for name in required:
            value = config[name]
            if (not isinstance(value, str) or not Path(value).is_absolute()
                    or any(ord(c) < 32 or ord(c) == 127 for c in value)):
                raise PairingError("已有 Steam/UU 网络配置包含无效路径。")
        for name in ("runner", "wrapper", "steam_real"):
            if not Path(config[name]).is_file() or not os.access(config[name], os.X_OK):
                raise PairingError("已有运行器、wrapper 或 Steam 程序不可用。")
        prefix = Path(config["prefix"])
        if (not (prefix / "pfx/system.reg").is_file()
                or not Path(config["uu_executable"]).is_file()
                or not Path(config["uu_executable"]).resolve().is_relative_to((prefix / "pfx").resolve())):
            raise PairingError("已有 UU 前缀或客户端尚未准备好。")
        network = (prefix / ".shorin-proton-wrapper.conf").read_text().splitlines()
        if [line for line in network if line.startswith("netns=")] != ["netns=1"]:
            raise PairingError("已有 UU 前缀未启用唯一的共享网络设置。")
        for name in ("routes.py", "cm_guard.py", "policy.py", "endpoints.py", "steam_window.py"):
            if not (self.helper.parent / name).is_file():
                raise PairingError("已有 Felix-Proton 启动组件不完整。")
        if not self.helper.is_file():
            raise PairingError("已有 Felix-Proton 启动入口不可用。")
        runtime = Path(config["runner"]).parent / "felix"
        for relative in ("local-beta.py", "observe.py", "net_beta.py",
                         "launchers/uu-network-launch", "launchers/uu-network-steam", "launchers/uu-network-run"):
            dependency = runtime / relative
            if (not dependency.is_file()
                    or relative.startswith("launchers/") and not os.access(dependency, os.X_OK)):
                raise PairingError("已有运行器的网络集成组件不完整，请先修复 Felix-Proton 设置。")
        identity = hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        connection = {key: config.get(key) for key in CONNECTION_KEYS}
        connection_identity = hashlib.sha256(json.dumps(connection, sort_keys=True,
                                                        separators=(",", ":")).encode()).hexdigest()
        return config_path, identity, connection_identity

    def _effective(self, name):
        user = self.apps / name
        if os.path.lexists(user):
            snapshot = self.desktop._snapshot(user)
            return user, self.desktop._content(snapshot), snapshot
        for directory in self.system_dirs:
            source = directory / name
            if source.is_file() and not source.is_symlink():
                data = source.read_bytes()
                if len(data) > 2 * 1024 * 1024:
                    raise PairingError("应用入口体积异常。")
                self.desktop._lines(data, name)
                return source, data, None
        raise PairingError("未找到 Steam 或网易 UU 的已安装应用入口。")

    def _wired(self, data, name):
        role = "steam" if name == PLATFORM_ID else "uu"
        command = "/usr/bin/python3 " + self.desktop._quote(self.helper) + " " + role
        entries = [(group, value) for _, group, key, value in
                   self.desktop._groups(self.desktop._lines(data, name))
                   if key == "Exec" and (group == "[Desktop Entry]" or
                       name == PLATFORM_ID and group.startswith("[Desktop Action "))]
        return (any(group == "[Desktop Entry]" for group, _ in entries)
                and len({group for group, _ in entries}) == len(entries)
                and all(value == command or name == PLATFORM_ID and
                        value.startswith((command + " ", command + "\t")) for _, value in entries))

    def _known_uu_entry(self, data):
        values = [value for _, group, key, value in
                  self.desktop._groups(self.desktop._lines(data, ACCELERATOR_ID))
                  if group == "[Desktop Entry]" and key == "Exec"]
        legacy = str(self.home / ".local/lib/uu-accelerator/launch")
        allowed = {"uu", self.desktop._quote(legacy)}
        if not any(character.isspace() for character in legacy):
            allowed.add(legacy)
        if len(values) != 1 or values[0] not in allowed:
            raise PairingError("UU 入口含自定义命令或参数，首版无法无损接入；已保留原入口，请先检查配置。")

    def _connected(self):
        try:
            return all(self._wired(self._effective(name)[1], name) for name in IDS)
        except (OSError, ValueError, RuntimeError):
            return False

    def _record(self):
        if not os.path.lexists(self.ledger):
            return None
        self._private_check()
        record = self._json(self.ledger, private=True)
        if (not isinstance(record, dict) or record.get("version") != 1
                or record.get("helper") != str(self.helper)
                or not isinstance(record.get("config"), str) or not Path(record["config"]).is_absolute()
                or not isinstance(record.get("config_identity"), str) or len(record["config_identity"]) != 64
                or any(c not in "0123456789abcdef" for c in record["config_identity"])
                or "connection_identity" in record and (
                    not isinstance(record["connection_identity"], str)
                    or len(record["connection_identity"]) != 64
                    or any(c not in "0123456789abcdef" for c in record["connection_identity"]))
                or record.get("phase") not in ("preparing", "paired", "removing", "recovery")
                or not isinstance(record.get("adopted"), bool)
                or not isinstance(record.get("files"), dict) or set(record["files"]) != set(IDS)):
            raise PairingError("配对记录与当前入口不符，已保留现有设置。")
        for entry in record["files"].values():
            if not isinstance(entry, dict) or set(entry) != {"before", "after"}:
                raise PairingError("配对记录不完整，已保留现有设置。")
            for snapshot in entry.values():
                if snapshot is None:
                    continue
                if (not isinstance(snapshot, dict) or set(snapshot) != {"data", "mode", "gid", "mtime", "attrs"}
                        or not isinstance(snapshot["mode"], int) or snapshot["mode"] & ~0o777
                        or not isinstance(snapshot["gid"], int) or not isinstance(snapshot["attrs"], dict)
                        or any(not key.startswith("user.") and key != "system.posix_acl_access"
                               for key in snapshot["attrs"])):
                    raise PairingError("配对备份格式无效，已保留现有设置。")
                self.desktop._content(snapshot)
        return record

    def _check_config(self, record, config, identity, connection_identity):
        matches = (record["connection_identity"] == connection_identity if "connection_identity" in record
                   else record["config_identity"] == identity)
        if record["config"] != str(config) or not matches:
            raise PairingError("配对所用的网络配置已变化；请先停止本工具管理，再重新配对。")

    def upgrade_record(self):
        """Add a connection-only fingerprint to an unchanged legacy record.

        Old recovery snapshots and the full fingerprint are retained. A legacy
        mismatch cannot be inferred safe from today's configuration, so refuse
        it instead of adopting a changed prefix. No desktop entry is written.
        """
        if not os.path.lexists(self.ledger):
            return False
        config, identity, connection_identity = self._prerequisites()
        with self._lock():
            record = self._record()
            if record is None or "connection_identity" in record:
                return False
            self._check_config(record, config, identity, connection_identity)
            self._verify_files(record)
            if record["phase"] != "paired":
                raise PairingError("配对尚未完成，已保留原恢复记录。")
            record["connection_identity"] = connection_identity
            self._save(record)
            return True

    def _private_check(self):
        info = self.private.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077):
            raise PairingError("配对记录目录必须由当前用户独占。")

    @contextmanager
    def _lock(self):
        self.private.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._private_check()
        fd = os.open(self.private / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "r+b") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise PairingError("配对锁文件权限异常。")
            fcntl.flock(stream, fcntl.LOCK_EX)
            yield

    def _save(self, record):
        self.desktop._atomic(self.ledger, (json.dumps(record, ensure_ascii=False) + "\n").encode())

    def _forget(self):
        self.ledger.unlink(missing_ok=True)
        self.desktop._syncdir(self.private)

    def _apply_snapshot(self, name, wanted, expected):
        target = self.apps / name
        current = self.desktop._snapshot(target)
        if self.desktop._same(current, wanted):
            return False
        if not self.desktop._same(current, expected):
            raise PairingError("应用入口已被其他程序或用户修改，已保留当前文件。")
        if wanted is None:
            target.unlink()
            self.desktop._syncdir(target.parent)
        else:
            self.desktop._atomic(target, self.desktop._content(wanted), wanted["mode"], wanted)
        return True

    def _verify_files(self, record):
        for name, entry in record["files"].items():
            current = self.desktop._snapshot(self.apps / name)
            sides = ("after",) if record["phase"] == "paired" else ("before", "after")
            if not any(self.desktop._same(current, entry[side]) for side in sides):
                raise PairingError("应用入口已被其他程序或用户修改，已保留当前文件。")

    def _finish_pair(self, record):
        self._verify_files(record)
        try:
            for name, entry in record["files"].items():
                self._apply_snapshot(name, entry["after"], entry["before"])
            record["phase"] = "paired"
            self._save(record)
        except Exception as error:
            recovered = True
            for name in reversed(tuple(record["files"])):
                entry = record["files"][name]
                try:
                    self._apply_snapshot(name, entry["before"], entry["after"])
                except Exception:
                    recovered = False
            if recovered:
                self._forget()
            else:
                record["phase"] = "recovery"
                self._save(record)
            raise PairingError("配对未完成；已回退本次可确认的修改。请重试或解除配对恢复。") from error

    def inspect(self):
        connected = self._connected()
        record = None
        try:
            config, identity, connection_identity = self._prerequisites()
            record = self._record()
            if record is not None:
                self._check_config(record, config, identity, connection_identity)
                self._verify_files(record)
            managed = record is not None
            adopted = bool(record and record["adopted"])
            if record and record["phase"] != "paired":
                message = "配对操作尚未完成，可重新配对或解除以恢复。"
            elif managed and adopted:
                message = "配对已保存。关闭本工具后仍然有效，日常直接使用原图标；停止管理会保留原有连接。"
            elif managed:
                message = "配对已保存。关闭工具或重启电脑后仍然有效，日常直接使用原图标。"
            elif connected:
                message = "已检测到现有 Steam 与网易 UU 连接，可拖拽配对后管理。"
            else:
                message = "将 Steam 和网易 UU 放到一起，即可关联已有共享网络。"
            ready = record is None or record["phase"] == "paired" and connected
            if managed and not connected and record["phase"] == "paired":
                message = "配对入口已发生变化，当前连接状态无法确认；可停止管理后重新配对。"
            return {"ready": ready, "connected": connected, "managed": managed,
                    "phase": record["phase"] if record else "unmanaged",
                    "adopted": adopted, "message": message}
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
            return {"ready": False, "connected": connected, "managed": os.path.lexists(self.ledger),
                    "phase": record["phase"] if record else "unavailable",
                    "adopted": bool(record and record["adopted"]),
                    "message": str(error) if isinstance(error, PairingError)
                    else "已有配置或桌面入口暂不可用，请先检查 Felix-Proton 设置。"}

    def pair(self, platform_id, accelerator_id):
        if (platform_id, accelerator_id) != IDS:
            raise PairingError("首版只支持原有 Steam 与网易 UU 图标的配对。")
        try:
            config, identity, connection_identity = self._prerequisites()
            self.apps.mkdir(parents=True, exist_ok=True)
            if self.apps.resolve() in {directory.resolve() for directory in self.system_dirs}:
                raise PairingError("用户应用目录与系统目录相同，不能修改。")
            if self.apps.stat().st_uid != os.getuid():
                raise PairingError("应用入口目录不属于当前用户。")
            with self._lock():
                record = self._record()
                if record is not None:
                    self._check_config(record, config, identity, connection_identity)
                    if record["phase"] in ("removing", "recovery"):
                        raise PairingError("上次操作尚需恢复，请先解除配对。")
                    self._verify_files(record)
                    if record["phase"] == "preparing":
                        self._finish_pair(record)
                    return self.inspect()
                files = {}
                wired = []
                for name in IDS:
                    _, data, before = self._effective(name)
                    already = self._wired(data, name)
                    wired.append(already)
                    if already:
                        after = before
                    else:
                        if name == ACCELERATOR_ID:
                            self._known_uu_entry(data)
                        role = "steam" if name == PLATFORM_ID else "uu"
                        command = "/usr/bin/python3 " + self.desktop._quote(self.helper) + " " + role
                        rewritten = self.desktop._rewrite(data, name, command, self.home, name == PLATFORM_ID)
                        after = self.desktop._changed(before, rewritten)
                    files[name] = {"before": before, "after": after}
                record = {"version": 1, "helper": str(self.helper), "config": str(config),
                          "config_identity": identity, "connection_identity": connection_identity,
                          "phase": "preparing", "adopted": all(wired), "files": files}
                self._save(record)
                self._finish_pair(record)
            return self.inspect()
        except PairingError:
            raise
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
            raise PairingError("无法完成配对，已保留已有应用和网络配置。") from error

    def remove(self):
        try:
            with self._lock():
                record = self._record()
                if record is None:
                    result = self.inspect()
                    result["message"] = "没有本工具管理的配对；现有网络设置保持不变。"
                    return result
                if record["adopted"]:
                    self._forget()
                    result = self.inspect()
                    result["message"] = "已停止管理；此前已有的 Steam/UU 网络设置仍然保留。"
                    return result
                self._verify_files(record)
                record["phase"] = "removing"
                self._save(record)
                for name, entry in record["files"].items():
                    self._apply_snapshot(name, entry["before"], entry["after"])
                self._forget()
            result = self.inspect()
            result["message"] = "已恢复本工具修改前的入口；正在运行的程序需正常退出后再启动。"
            return result
        except PairingError:
            raise
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
            raise PairingError("解除尚未完成，恢复记录已保留；请检查权限后重试。") from error
