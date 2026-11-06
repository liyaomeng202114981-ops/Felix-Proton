# SPDX-License-Identifier: BSD-3-Clause
"""Prepare the existing test.1 runtime and its private UU prefix configuration."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

import bootstrap

SetupError = bootstrap.SetupError
VERSION = "0.1.0-test.1"
OWNER = "Felix UU " + VERSION
CLIENT = Path("pfx/drive_c/Program Files (x86)/Netease/UU/uu_launcher.exe")
PENDING = ".felix-native-prefix-pending"
# From the original SHA-locked test.1 tar. These small files also identify an
# already installed runner when the installer archive is no longer available.
IDENTITY = {
    "felix-build.json": "bffbe2b25c7d18191f617c8f0a1fc61c1b24cc0dc825bf95d7f22102a72a80b7",
    "proton": "85af7e90a49e54ca59ce71aec0fd83cb37adb89e968f0cf756d785967969fe3c",
    "files/lib/wine/x86_64-unix/nsiproxy.so": "d5c538f1eda8d9bbb11c79afbc5f4e01303d5c0ee18a1173ec52c8356202e807",
    "files/lib/wine/i386-unix/nsiproxy.so": "81dd705bd950bc8bb58fe5676265579522a7c0a789c21af4d79d970621323f3a",
}


def _directory(path, private=False):
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or private and info.st_mode & 0o077):
        raise SetupError(f"无法确认此目录的归属或权限：{path}")


def _data(path):
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077 or info.st_size > 65536):
        raise SetupError(f"配置文件的类型、权限或归属不符：{path.name}")
    return path.read_text(encoding="utf-8")


def _validate_prefix(prefix):
    _directory(prefix, private=True)
    if _data(prefix/".felix-uu-test-owner").strip() != OWNER:
        raise SetupError("UU 前缀没有此版本的归属标记。")
    net = [l for l in _data(prefix/".shorin-proton-wrapper.conf").splitlines() if l.startswith("netns=")]
    if net != ["netns=1"]:
        raise SetupError("已有 UU 前缀没有启用唯一的独立网络设置。")
    if os.path.lexists(prefix/"pfx"):
        _directory(prefix/"pfx")


def _validate_config(cfg, prefix, runner):
    keys = {"prefix", "runner", "wrapper", "steam_real", "uu_executable", "uu_locale",
            "pasta_bin_dir", "desktop_wrapper"}
    required = {"prefix", "runner", "wrapper", "steam_real"}
    if not isinstance(cfg, dict) or not required <= cfg.keys() <= keys:
        raise SetupError("已有配置字段不符合 Felix UU test.1。")
    for key, value in cfg.items():
        if (not isinstance(value, str) or not value or any(ord(c)<32 for c in value)
                or key != "uu_locale" and not Path(value).is_absolute()):
            raise SetupError(f"已有配置字段无效：{key}")
    if Path(cfg["prefix"]).resolve() != prefix.resolve() or Path(cfg["runner"]).resolve() != runner:
        raise SetupError("已有配置中的 UU 前缀或运行器不同。")
    if not Path(cfg.get("uu_executable", prefix/CLIENT)).resolve().is_relative_to((prefix/"pfx").resolve()):
        raise SetupError("配置中的 UU 客户端路径不在专用 Wine 前缀中。")
    if Path(cfg["steam_real"]) == prefix.parent.parent/".local/bin/steam" or Path(cfg["steam_real"]).resolve() in {
            (prefix.parent.parent/".local/lib/uu-accelerator/steam").resolve(),
            (runner.parent/"felix/launchers/uu-network-steam").resolve(),
            (runner.parent/"felix/local-beta.py").resolve()}:
        raise SetupError("Steam 实际入口不能回指测试启动器或用户 PATH 代理。")
    for name in ("wrapper", "steam_real", "desktop_wrapper"):
        if name in cfg and not (Path(cfg[name]).is_file() and os.access(cfg[name], os.X_OK)):
            raise SetupError(f"已配置的 {name} 不可执行。")


def _check_identity(runner):
    root = runner.parent
    if root.name != bootstrap.TOOL or root.is_symlink() or not os.access(runner, os.X_OK):
        raise SetupError("运行器路径或可执行权限与 test.1 不符。")
    for rel, digest in IDENTITY.items():
        p = root/rel
        if p.is_symlink() or not p.is_file() or p.stat().st_size > 2*1024*1024:
            raise SetupError("缺少可核验的 test.1 组件。")
        if hashlib.sha256(p.read_bytes()).hexdigest() != digest:
            raise SetupError(f"现有运行器与原始 test.1 不符：{rel}")


def _publish_directory(path, files):
    # Everything is prepared privately, then published without overwriting a
    # competing install. Never rename over an initialized prefix.
    with tempfile.TemporaryDirectory(dir=path.parent, prefix=".felix-setup-") as tmp:
        staged = Path(tmp)
        for name, text in files.items():
            f = staged/name
            f.write_text(text, encoding="utf-8")
            f.chmod(0o600)
        bootstrap._rename_new(staged, path)


def _report_or_raise(report):
    if not report["ready"]:
        raise SetupError("\n".join(report["issues"]))
    return report


def ensure_config(archive: Path | None = None, *, home=None, steam_root=None, wrapper=None,
                  pasta=None, steam=None, uu_installer=None) -> Path:
    """Reuse owned state or install the pinned archive and create config. No desktop edits."""
    home = (Path.home() if home is None else Path(home)).expanduser().resolve()
    prefix = home/"Games"/("Felix-UU-" + VERSION)
    xdg = Path(os.environ.get("XDG_CONFIG_HOME") or home/".config")
    if not xdg.is_absolute():
        xdg = home/".config"
    parent = xdg/"felix-uu-test"
    folder = parent/VERSION
    config = folder/"config.json"
    options = dict(steam_root=steam_root, home=home, wrapper=wrapper, pasta=pasta,
                   steam=steam, uu_installer=uu_installer)
    try:
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _directory(parent)
        fd = os.open(parent, os.O_DIRECTORY | os.O_NOFOLLOW | os.O_RDONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            existing = os.path.lexists(folder)
            pending = folder/PENDING
            if existing:
                _directory(folder, private=True)
                recovering = os.path.lexists(pending)
                if recovering and _data(pending) != OWNER+"\n":
                    raise SetupError("未完成的配置标记无法识别。")
                if os.path.lexists(prefix):
                    _validate_prefix(prefix)
                elif not recovering:
                    raise SetupError("已有配置缺少对应的专用前缀，请检查原安装。")
                cfg = json.loads(_data(config))
                manifest = folder/"owned-files.json"
                if os.path.lexists(manifest):
                    saved = json.loads(_data(manifest))
                    if not isinstance(saved, dict) or saved.get("owner") != OWNER:
                        raise SetupError("已有安装清单不属于此版本。")
                expected_root = bootstrap._native_root(home, steam_root)
                if expected_root is None:
                    raise SetupError("找不到已有试用版对应的原生 Steam 根目录。")
                expected_runner = expected_root/"compatibilitytools.d"/bootstrap.TOOL/"proton"
                _validate_config(cfg, prefix, expected_runner)
                _check_identity(expected_runner)
                for key, path in (("wrapper", cfg.get("wrapper")), ("steam", cfg.get("steam_real")),
                                  ("pasta", Path(cfg["pasta_bin_dir"])/"pasta" if "pasta_bin_dir" in cfg else None)):
                    if path and options[key] is not None and Path(options[key]).resolve() != Path(path).resolve():
                        raise SetupError(f"指定的 {key} 与已有配置不同，已保留原配置。")
                    if path:
                        options[key] = path
                report = _report_or_raise(bootstrap.discover(**options))
                if Path(report["runner"]) != expected_runner:
                    raise SetupError("Steam 根目录在检查期间发生变化。")
                if not recovering:
                    return config
            else:
                if os.path.lexists(prefix):
                    raise SetupError("已有同名 UU 前缀但缺少本版配置，已保留原目录。")
                if archive is None:
                    raise SetupError("首次安装需要原始 test.1 运行器归档。")
                report = _report_or_raise(bootstrap.prepare(archive, **options))
                runner = Path(report["runner"])
                _check_identity(runner)
                cfg = {"prefix":str(prefix), "runner":str(runner), "wrapper":report["wrapper"],
                       "steam_real":report["steam_real"], "pasta_bin_dir":report["pasta_bin_dir"],
                       "uu_executable":str(prefix/CLIENT), "uu_locale":"zh_CN.UTF-8"}
                _validate_config(cfg, prefix, runner)
                _publish_directory(folder, {"config.json":json.dumps(cfg, ensure_ascii=False, indent=2)+"\n",
                                             PENDING:OWNER+"\n"})
            if not os.path.lexists(prefix):
                prefix.parent.mkdir(parents=True, exist_ok=True)
                _publish_directory(prefix, {".felix-uu-test-owner":OWNER+"\n",
                                            ".shorin-proton-wrapper.conf":"netns=1\n"})
            _validate_prefix(prefix)
            pending.unlink()
            return config
        finally:
            os.close(fd)
    except (OSError, RuntimeError, ValueError, TypeError, AttributeError) as exc:
        raise SetupError(f"准备试用版配置失败：{exc}") from exc
