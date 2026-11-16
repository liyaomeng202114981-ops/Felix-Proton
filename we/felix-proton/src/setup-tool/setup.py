#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Prepare fixed Felix-Proton materials, then run the existing user installer."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
NATIVE = HERE.parent / "native-ux"
PAIRING = HERE.parent / "pairing-tool"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(NATIVE))
import bootstrap
import enable
import routes
import setup_config
import icons

VERSION = "0.1.0-preview.1"
RELEASE_TAG = "felix-proton-setup-v" + VERSION
DOWNLOAD_BASE = ("https://github.com/liyaomeng202114981-ops/Felix-Proton/releases/download/"
                 + RELEASE_TAG + "/")
MISSING_WRAPPER = "缺少支持 --netns、--prefix 和 --runner 的 shorin-proton-wrapper，可用 --wrapper 指定。"
MISSING_PASTA = "缺少试用版验证过的 pasta 功能（包括 --no-pidns）。可用 --pasta 指向合适版本。"
SetupError = bootstrap.SetupError


def xdg(name, fallback):
    value = Path(os.environ.get(name) or Path.home() / fallback)
    return value if value.is_absolute() else Path.home() / fallback


def secure_directory(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077):
        raise SetupError("目录类型、归属或私有权限不符，已保留：" + str(path))
    return path


def require_user_home():
    if os.geteuid() == 0:
        raise SetupError("请以普通桌面用户运行安装器，不要使用 sudo/root。")
    home = Path.home()
    info = home.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise SetupError("HOME 目录不属于当前用户，拒绝写入其他用户环境。")


def read_manifest(path=HERE / "downloads.json"):
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > 65536:
        raise SetupError("发行下载清单不是受支持的普通文件。")
    data = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or data.get("schema") != "felix-setup-downloads-v1"
            or not isinstance(data.get("assets"), dict)
            or set(data.get("assets", {})) != {"runner", "wrapper", "pasta"}):
        raise SetupError("发行下载清单版本或文件集合不符。")
    for kind, asset in data["assets"].items():
        if (not isinstance(asset, dict) or set(asset) != {"filename", "url", "sha256", "max_bytes"}
                or not isinstance(asset["filename"], str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,160}", asset["filename"])
                or not isinstance(asset["sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", asset["sha256"])
                or type(asset["max_bytes"]) is not int
                or not 0 < asset["max_bytes"] <= 2 * 1024**3
                or asset["url"] != DOWNLOAD_BASE + asset["filename"]):
            raise SetupError("发行下载清单的地址、哈希或体积上限不符：" + kind)
    runner = data["assets"]["runner"]
    if runner["filename"] != bootstrap.ARCHIVE or runner["sha256"] != bootstrap.SHA256:
        raise SetupError("下载清单不能改变固定 test.1 运行器身份。")
    return data["assets"]


def verify_file(path, asset, *, owned=False):
    """Hash a regular, unchanged file without following a final symlink."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_size > asset["max_bytes"]
                or owned and (before.st_uid != os.getuid() or before.st_mode & 0o022)):
            raise SetupError("材料文件的类型、归属或体积不符：" + str(path))
        stream = os.fdopen(fd, "rb")
        fd = None
        with stream:
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
            after = os.fstat(stream.fileno())
            if ((before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                    != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                    or digest.hexdigest() != asset["sha256"]):
                raise SetupError("材料 SHA-256 不符或校验期间发生变化，已保留：" + str(path))
    finally:
        if fd is not None:
            os.close(fd)
    return Path(path)


def obtain(asset, *, offline=False, cache=None, opener=None, local_dirs=None):
    """Reuse exact local material, or atomically publish one verified HTTPS download."""
    directories = local_dirs if local_dirs is not None else (
        HERE / "assets", HERE, HERE.parent, HERE.parent.parent, Path.home() / "Downloads")
    for directory in directories:
        candidate = Path(directory) / asset["filename"]
        if os.path.lexists(candidate):
            return verify_file(candidate, asset)
    if cache is None:
        cache_root = xdg("XDG_CACHE_HOME", ".cache") / "felix-proton-setup"
        cache = cache_root / "v1"
    else:
        cache_root = None
        cache = Path(cache)
    target = cache / asset["filename"]
    if os.path.lexists(target):
        return verify_file(target, asset, owned=True)
    if offline:
        raise SetupError("离线材料缺失：" + asset["filename"])
    if cache_root is not None:
        secure_directory(cache_root)
    secure_directory(cache)
    opener = urllib.request.urlopen if opener is None else opener
    print("正在下载并校验 " + asset["filename"], file=sys.stderr, flush=True)
    request = urllib.request.Request(asset["url"], headers={"User-Agent": "Felix-Proton-Setup/" + VERSION})
    temporary = None
    try:
        with opener(request, timeout=30) as response:
            final = urllib.parse.urlsplit(response.geturl())
            if (final.scheme != "https" or final.username or final.password or final.port not in (None, 443)
                    or final.hostname not in
                    {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}):
                raise SetupError("下载重定向不属于受支持的 HTTPS 发行服务。")
            length = response.headers.get("Content-Length")
            if length is not None and (not length.isdigit() or int(length) > asset["max_bytes"]):
                raise SetupError("下载响应超过材料体积上限。")
            with tempfile.NamedTemporaryFile(prefix=".download-", dir=cache, delete=False) as output:
                temporary = Path(output.name)
                digest, total = hashlib.sha256(), 0
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > asset["max_bytes"]:
                        raise SetupError("下载内容超过材料体积上限。")
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if digest.hexdigest() != asset["sha256"]:
                raise SetupError("下载材料 SHA-256 不符，未安装。")
            try:
                os.link(temporary, target)  # no overwrite if another setup won the race
            except FileExistsError:
                verify_file(target, asset, owned=True)
            return verify_file(target, asset, owned=True)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def install_dependency(kind, source, asset, *, data_home=None):
    base = Path(data_home) if data_home else xdg("XDG_DATA_HOME", ".local/share")
    app = secure_directory(base / "felix-proton-setup")
    folder = secure_directory(app / "dependencies-v1")
    version = secure_directory(folder / (kind + "-" + asset["sha256"][:16]))
    target = version / ("shorin-proton-wrapper" if kind == "wrapper" else "pasta")
    if os.path.lexists(target):
        verify_file(target, asset, owned=True)
        if not os.access(target, os.X_OK):
            raise SetupError("已有依赖缺少执行权限，已保留：" + str(target))
        return target
    verify_file(source, asset)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".dependency-", dir=version, delete=False) as output:
            temporary = Path(output.name)
            with Path(source).open("rb") as stream:
                shutil.copyfileobj(stream, output, length=1024 * 1024)
            output.flush()
            os.fsync(output.fileno())
        verify_file(temporary, asset, owned=True)
        temporary.chmod(0o755)
        try:
            os.link(temporary, target)
        except FileExistsError:
            verify_file(target, asset, owned=True)
        return target
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def options(args):
    return {key: getattr(args, key, None) for key in ("steam_root", "wrapper", "pasta", "steam", "uu_installer")}


def discover_options(args):
    """Read owned, version-checked dependency defaults without modifying setup state."""
    found = options(args)
    file = xdg("XDG_CONFIG_HOME", ".config") / "felix-uu-test" / setup_config.VERSION / "config.json"
    if not os.path.lexists(file):
        return found
    setup_config._directory(file.parent, private=True)
    cfg = json.loads(setup_config._data(file))
    if not isinstance(cfg, dict) or not isinstance(cfg.get("runner"), str):
        raise SetupError("已有配置缺少固定运行器路径，已保留。")
    runner = Path(cfg["runner"])
    if not runner.is_absolute() or runner.parent.parent.name != "compatibilitytools.d":
        raise SetupError("已有配置运行器不在 Steam 的固定安装目录中。")
    prefix = Path.home() / "Games" / ("Felix-UU-" + setup_config.VERSION)
    setup_config._validate_prefix(prefix)
    setup_config._check_identity(runner)
    setup_config._validate_config(cfg, prefix, runner)
    saved = {"wrapper": cfg["wrapper"], "steam": cfg["steam_real"],
             "steam_root": str(runner.parent.parent.parent)}
    if "pasta_bin_dir" in cfg:
        saved["pasta"] = str(Path(cfg["pasta_bin_dir"]) / "pasta")
    for key, value in saved.items():
        if found[key] is not None and Path(found[key]).expanduser().resolve() != Path(value).resolve():
            raise SetupError("指定的 " + key + " 与已有配置不同，已保留原配置。")
        found[key] = Path(value)
    return found


def frontend_issues():
    """Check the actual interpreter used by installed launchers without opening a GUI."""
    checks = (
        ("import gi; gi.require_version('Gtk','4.0'); gi.require_version('Adw','1'); "
         "gi.require_version('GdkPixbuf','2.0'); from gi.repository import GdkPixbuf; "
         "assert any(f.get_name() == 'ico' for f in GdkPixbuf.Pixbuf.get_formats()); "
         "from gi.repository import Gtk, Adw; "
         "assert (Gtk.get_major_version(), Gtk.get_minor_version()) >= (4,10); "
         "assert (Adw.get_major_version(), Adw.get_minor_version()) >= (1,4)",
         "配对界面需要 /usr/bin/python3 可用的 PyGObject、GTK 4.10+、libadwaita 1.4+ 和支持 ICO 的 GdkPixbuf。"),
        ("import locale; locale.setlocale(locale.LC_CTYPE,'zh_CN.UTF-8')",
         "此固定版本需要系统提供 zh_CN.UTF-8 locale；请先按发行版说明生成该语言环境。"),
    )
    issues = []
    for script, message in checks:
        try:
            result = subprocess.run(["/usr/bin/python3", "-B", "-c", script],
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=10, check=False)
            if result.returncode:
                issues.append(message)
        except (OSError, subprocess.TimeoutExpired):
            issues.append(message)
    return issues


def check(args):
    try:
        require_user_home()
    except SetupError as error:
        return {"ready": False, "host_ready": False, "issues": [str(error)], "warnings": [],
                "automatic_materials": [], "requires_official_uu_installer": not bool(args.uu_installer)}
    report = bootstrap.discover(**discover_options(args))
    automatic = [name for name, key in (("wrapper", "wrapper"), ("pasta", "pasta_bin_dir"))
                 if not report[key] and not getattr(args, name)]
    movable = {MISSING_WRAPPER if name == "wrapper" else MISSING_PASTA for name in automatic}
    report["issues"] = [message for message in report["issues"] if message not in movable]
    report["issues"].extend(frontend_issues())
    if "pasta" in automatic:
        try:
            libc = re.fullmatch(r"glibc ([0-9]+)\.([0-9]+)", os.confstr("CS_GNU_LIBC_VERSION") or "")
        except (OSError, ValueError):
            libc = None
        if libc is None or tuple(map(int, libc.groups())) < (2, 38):
            report["issues"].append("本版自动提供的 pasta 需要 glibc 2.38+；请用 --pasta 指定已验证兼容且功能齐全的版本，或使用符合要求的系统。")
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        report["issues"].append("请在已登录的 Linux 图形桌面中运行，以便完成官方 UU 安装界面。")
    for tool in ("tar", "xz"):
        if not shutil.which(tool):
            report["issues"].append("Steam Linux Runtime 初始化需要系统工具 " + tool + "。")
    if not any(shutil.which(tool) for tool in ("curl", "wget")):
        report["issues"].append("Steam Linux Runtime 首次下载需要 curl 或 wget。")
    for tool, message in (("notify-send", "缺少 notify-send，连接保护的桌面成功/失败通知将不可用。"),
                          ("wmctrl", "缺少 wmctrl，已有 Steam 窗口唤出将使用 URI 回退。"),
                          ("xprop", "缺少 xprop，已有 Steam 窗口唤出将使用 URI 回退。")):
        if not shutil.which(tool):
            report["warnings"].append(message)
    for path in ("/usr/bin/nsenter", "/usr/sbin/ip"):
        if not os.path.isfile(path) or not os.access(path, os.X_OK):
            report["issues"].append("连接保护需要可执行的 " + path + "。")
    report["ready"] = not report["issues"]
    report["host_ready"] = report["ready"]
    report["automatic_materials"] = automatic
    report["requires_official_uu_installer"] = not bool(args.uu_installer)
    return report


def brand_icon(ctx):
    data = xdg("XDG_DATA_HOME", ".local/share")
    user_entry = data / "applications/uu-accelerator.desktop"
    system = [Path(path) / "applications/uu-accelerator.desktop"
              for path in (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
              if path.startswith("/")]
    if os.path.lexists(user_entry) or any(path.is_file() for path in system):
        return None  # Desktop takeover preserves an existing entry's original Icon.
    return icons.install_icon(ctx.client, data)


def install(args):
    require_user_home()
    assets = read_manifest()
    if not (PAIRING / "install.py").is_file():
        raise SetupError("发行目录缺少配对工具，请完整解压安装包。")
    existing = (xdg("XDG_CONFIG_HOME", ".config") / "felix-uu-test" / setup_config.VERSION / "config.json")
    # Resume an owned installation through its existing dependency paths; do not
    # silently change its wrapper or runner when the user only reruns setup.
    has_config = os.path.lexists(existing)
    archive = args.runner_archive.expanduser() if args.runner_archive is not None else None
    if not has_config and not args.uu_installer:
        raise SetupError("首次安装需 --uu-installer 指定从网易 UU 官方下载的 Windows .exe；不分发客户端或账号。")
    if args.uu_installer:
        bootstrap.inspect_installer(args.uu_installer)  # reject invalid input before any download
    with enable.operation():
        native_options = options(args)
        if not has_config:
            report = check(args)
            ignored = set()
            if not args.wrapper:
                ignored.add(MISSING_WRAPPER)
            if not args.pasta:
                ignored.add(MISSING_PASTA)
            issues = [message for message in report["issues"] if message not in ignored]
            if issues:
                raise SetupError("\n".join(issues))
            for message in report.get("warnings", []):
                print(message, file=sys.stderr)
            for kind, key in (("wrapper", "wrapper"), ("pasta", "pasta_bin_dir")):
                if not report[key]:
                    material = obtain(assets[kind], offline=args.offline)
                    native_options[kind] = install_dependency(kind, material, assets[kind])
            if archive is None:
                archive = obtain(assets["runner"], offline=args.offline)
        if archive is not None:
            verify_file(Path(archive), assets["runner"])
        forwarded = argparse.Namespace(archive=archive, uu_icon_provider=brand_icon, **native_options)
        print("材料检查完成。接下来初始化专用 Windows 前缀并打开官方 UU 安装界面；完成安装后才接入原图标。",
              file=sys.stderr, flush=True)
        result = enable.enable(forwarded)
        if result.get("changed"):
            enable.refresh()
    # A separate process avoids native desktop/backend module name collisions.
    completed = subprocess.run([sys.executable, "-B", str(PAIRING / "install.py")],
                               check=False, capture_output=True, text=True)
    if completed.returncode:
        if completed.stderr:
            print(completed.stderr[-4096:], file=sys.stderr)
        raise SetupError("底层集成已安装，但配对工具菜单安装未完成。保留现有前缀和入口，修正报错后可重新运行。")
    return {"ready": True, "version": VERSION, "desktop": result,
            "pairing_tool_installed": True,
            "next": "在官方客户端内完成登录；日常使用原 Steam/网易 UU 图标，工具中可一次登记已有连接。"}


def parser():
    result = argparse.ArgumentParser(description="从零准备 Felix-Proton Steam/UU 共享网络与配对工具")
    result.add_argument("action", choices=("check", "install", "status", "restore"), nargs="?", default="check")
    result.add_argument("--runner-archive", type=Path, help="本地原始 test.1 归档；缺省按发行清单下载")
    result.add_argument("--uu-installer", type=Path, help="从网易 UU 官方下载的 Windows 安装程序")
    for name in ("steam-root", "wrapper", "pasta", "steam"):
        result.add_argument("--" + name, type=Path)
    result.add_argument("--offline", action="store_true", help="只使用已核验本地材料，不发起下载")
    result.add_argument("--json", action="store_true", help="以 JSON 输出检查或完成结果")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.action == "check":
            report = check(args)
        elif args.action == "install":
            report = install(args)
        elif args.action == "status":
            report = routes.state(routes.load())
        else:
            require_user_home()
            with enable.operation():
                report = enable.desktop.restore(enable.statedir())
                if report.get("changed"):
                    enable.refresh()
        if args.json or args.action == "status":
            print(json.dumps(report, ensure_ascii=False, default=str, indent=2))
        elif args.action == "check":
            print("本机前置检查通过。" if report["ready"] else "本机前置条件尚未满足：")
            for issue in report["issues"]:
                print("- " + issue)
            if report["automatic_materials"]:
                print("安装时将自动下载并校验：" + "、".join(report["automatic_materials"]) + "。")
            for warning in report["warnings"]:
                print("提示：" + warning)
            if report["requires_official_uu_installer"]:
                print("全新安装请先从网易 UU 官方下载 Windows 安装程序，并用 --uu-installer 指定。")
        elif args.action == "install":
            print("安装完成。请在官方客户端内完成登录，日常继续使用原来的 Steam 和网易 UU 图标。")
            print("“Felix 配对”已加入应用菜单，可打开后一次登记已有连接；不需常驻。")
        else:
            print("已按备份恢复本工具接入的桌面入口；前缀、客户端和登录数据均保留。")
        if args.action == "check":
            return 0 if report["ready"] else 1
        return 0
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, SetupError) as error:
        text = str(error)
        print(json.dumps({"ready": False, "issues": [text]}, ensure_ascii=False) if args.json else text,
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
