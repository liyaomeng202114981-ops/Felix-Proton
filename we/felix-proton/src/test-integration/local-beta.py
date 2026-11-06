#!/usr/bin/python3
# SPDX-License-Identifier: BSD-3-Clause
"""Personal setup and launch gate for Felix UU 0.1.0-test.1."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

VERSION = "0.1.0-test.1"
PACKAGE = "felix-proton-uu-test-" + VERSION
SETUP_SHA256 = "3c5df7f4e2386635b0fb8e9dd7c88ffa6546cfcf39b72f0319260ad810d8b5e5"
OWNER = "Felix UU " + VERSION
CONFIG_OVERRIDES = ("UU_NETWORK_CONFIG", "UU_PREFIX", "UU_RUNNER", "UU_WRAPPER",
                    "UU_EXE", "UU_PASTA_BIN_DIR", "UU_LOCALE", "UU_DESKTOP_WRAPPER", "STEAM_REAL")


class Refused(Exception):
    def __init__(self, message, reason="prepare"):
        super().__init__(message)
        self.reason = reason


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    if path.is_symlink():
        raise Refused("配置文件是符号链接，请检查测试版安装目录。")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise Refused("测试版配置不可读，请运行 install 检查安装。") from exc


def create_only(path, data, mode=0o600):
    """Publish complete content without replacing another path or following a symlink."""
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".felix-uu-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            os.fchmod(stream.fileno(), mode)
        # Link a newly written staging file, never a file from an existing prefix.
        os.link(temporary, path)
    finally:
        os.unlink(temporary)


def quoted_desktop_path(path):
    text = str(path)
    if any(ord(c) < 32 for c in text):
        raise Refused("测试版安装路径含换行或控制字符。")
    # First quote one Exec argument, then escape the desktop-entry string value.
    value = "".join("\\" + c if c in '\\"$`' else c for c in text)
    return '"' + value.replace("\\", "\\\\").replace("%", "%%") + '"'


class Beta:
    def __init__(self, root=None, home=None):
        self.home = Path.home() if home is None else Path(home)
        self.root = Path(__file__).resolve().parent.parent if root is None else Path(root)
        self.prefix = self.home / "Games" / ("Felix-UU-" + VERSION)
        self.stable = self.home / "Games/UU-Accelerator"
        self.runner = self.root / "proton"
        self.felix = self.root / "felix"
        self.portable = self.felix / "launchers"
        self.observer = self.felix / "observe.py"
        config_base = Path(os.environ.get("XDG_CONFIG_HOME", "") or self.home / ".config")
        data_base = Path(os.environ.get("XDG_DATA_HOME", "") or self.home / ".local/share")
        self.config = config_base / "felix-uu-test" / VERSION / "config.json"
        self.manifest = self.config.with_name("owned-files.json")
        self.apps = data_base / "applications"
        self.marker = self.prefix / ".felix-uu-test-owner"
        self.network_config = self.prefix / ".shorin-proton-wrapper.conf"
        self.client = self.prefix / "pfx/drive_c/Program Files (x86)/Netease/UU/uu_launcher.exe"
        self.installer = self.home / "Downloads/UU-official-setup.exe"

    def config_defaults(self):
        local = self.home / ".local"
        wrapper = local / "bin/shorin-proton-wrapper"
        font = local / "lib/steam-updater-font/launch"
        pasta_dir = local / "lib/uu-accelerator/bin"
        desktop = local / "bin/we-proton-desktop"
        cfg = {"prefix": str(self.prefix), "runner": str(self.runner),
               "wrapper": str(wrapper if wrapper.is_file() else shutil.which("shorin-proton-wrapper") or wrapper),
               "steam_real": str(font if os.access(font, os.X_OK) else "/usr/bin/steam"),
               "uu_executable": str(self.client), "uu_locale": "zh_CN.UTF-8"}
        if os.access(pasta_dir / "pasta", os.X_OK):
            cfg["pasta_bin_dir"] = str(pasta_dir)
        if os.access(desktop, os.X_OK):
            cfg["desktop_wrapper"] = str(desktop)
        return cfg

    def desktop_files(self):
        script = quoted_desktop_path(self.felix / "local-beta.py")
        result = {}
        for mode, name, comment, icon in [
            ("uu", "网易 UU（Felix 测试版）", "打开测试版加速器", "network-vpn"),
            ("steam", "Steam（Felix UU 测试版）", "在测试版 UU 网络中打开 Steam", "steam"),
        ]:
            path = self.apps / f"felix-uu-{VERSION}-{mode}.desktop"
            result[path] = (f"[Desktop Entry]\nType=Application\nName={name}\nComment={comment}\n"
                            f"Exec=/usr/bin/python3 {script} {mode}\nIcon={icon}\nTerminal=false\n"
                            "Categories=Network;\nStartupNotify=false\nActions=MarkIssue;\n\n"
                            f"[Desktop Action MarkIssue]\nName=标记刚才异常\nExec=/usr/bin/python3 {script} mark\n").encode()
        return result

    def verify_layout(self):
        expected = self.home / ".local/share/Steam/compatibilitytools.d" / PACKAGE
        if self.root.resolve() != expected.resolve() or self.root.is_symlink():
            raise Refused(f"请先将运行器放到 {expected}，再设置本机入口。")
        for path in (self.runner, self.portable / "uu-network-launch", self.portable / "uu-network-steam"):
            if not path.is_file() or not os.access(path, os.X_OK):
                raise Refused("测试版运行器或启动脚本未准备好。")
        if not self.observer.is_file() or not (self.portable / "uu_network.py").is_file():
            raise Refused("测试版缺少监测器或启动模块。")
        if any(p.is_symlink() for p in (self.prefix, self.prefix / "pfx", self.config.parent, self.marker, self.network_config)):
            raise Refused("测试版专用目录或配置指向了其他位置。")
        if self.prefix.resolve() == self.stable.resolve():
            raise Refused("测试版前缀与稳定版前缀相同。", "mixed-runner")
        if self.prefix.exists() and self.prefix.stat().st_uid != os.getuid():
            raise Refused("测试版前缀不属于当前用户。")

    def install(self):
        self.verify_layout()
        desktops = self.desktop_files()
        files = {self.config: (json.dumps(self.config_defaults(), ensure_ascii=False, indent=2) + "\n").encode(),
                 self.marker: (OWNER + "\n").encode(), self.network_config: b"netns=1\n", **desktops}
        # Record the intended files before publishing them, so an interrupted
        # install can fill in missing files on retry without adopting strangers.
        if self.manifest.is_symlink():
            raise Refused("安装记录是符号链接。")
        if self.manifest.exists():
            saved = read_json(self.manifest)
            if not isinstance(saved, dict) or saved.get("owner") != OWNER or set(saved.get("files", {})) != {str(p) for p in files}:
                raise Refused("已有测试版安装记录无法识别。")
        else:
            if self.config.exists() or self.config.is_symlink() or any(p.exists() or p.is_symlink() for p in desktops):
                raise Refused("测试版入口或配置已被占用，请检查同名文件。")
            if self.prefix.exists() and any(self.prefix.iterdir()):
                raise Refused("测试版前缀已有其他数据，请检查其来源。")
            self.config.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            saved = {"owner": OWNER, "files": {str(p): digest(data) for p, data in files.items()}}
            create_only(self.manifest, (json.dumps(saved, ensure_ascii=False, indent=2) + "\n").encode())
        self.prefix.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.prefix.stat().st_mode & 0o077:
            raise Refused("测试版前缀需仅当前用户可访问，请检查目录权限。")
        for path, data in files.items():
            if path.is_symlink():
                raise Refused("测试版目标位置出现符号链接。")
            if path.exists():
                if path == self.config:
                    self.read_config()  # Keep a valid personal configuration.
                elif path == self.network_config:
                    if b"netns=1" not in path.read_bytes().split(b"\n"):
                        raise Refused("测试版前缀没有开启独立网络。")
                elif digest(path.read_bytes()) != saved["files"][str(path)]:
                    raise Refused(f"已有文件经过修改，保留原文件：{path.name}")
            elif digest(data) == saved["files"][str(path)]:
                create_only(path, data, 0o644 if path in desktops else 0o600)
            else:
                raise Refused(f"安装时的依赖与现状不一致，请检查 {path.name}。")
        return "已创建测试版独立入口。首次打开“网易 UU（Felix 测试版）”会进入安装。"

    def uninstall(self):
        if not self.manifest.is_file():
            raise Refused("没有找到本版本的安装记录。")
        saved = read_json(self.manifest)
        if not isinstance(saved, dict) or saved.get("owner") != OWNER:
            raise Refused("安装记录无法识别。")
        desktops = self.desktop_files()
        for path in desktops:
            if path.is_symlink() or (path.exists() and digest(path.read_bytes()) != saved.get("files", {}).get(str(path))):
                raise Refused(f"桌面入口经过修改，已保留：{path.name}")
        for path in desktops:
            path.unlink(missing_ok=True)
        return "已移除测试版桌面入口。个人配置、测试前缀和诊断记录已保留。"

    def read_config(self):
        cfg = read_json(self.config)
        allowed = {"prefix", "runner", "wrapper", "steam_real", "uu_executable", "pasta_bin_dir", "uu_locale", "desktop_wrapper"}
        if (not isinstance(cfg, dict) or set(cfg) - allowed or
                any(not isinstance(v, str) or not v or any(ord(c) < 32 for c in v) for v in cfg.values())):
            raise Refused("测试版配置格式错误。")
        for field, wanted in (("prefix", self.prefix), ("runner", self.runner)):
            if not isinstance(cfg.get(field), str) or Path(cfg[field]).expanduser().resolve() != wanted.resolve():
                raise Refused("测试版配置中的运行器或前缀不匹配。", "mixed-runner")
        exe = cfg.get("uu_executable", str(self.client))
        if not isinstance(exe, str) or not Path(exe).expanduser().resolve().is_relative_to((self.prefix / "pfx").resolve()):
            raise Refused("UU 程序必须安装在测试版自己的前缀中。", "mixed-runner")
        steam = Path(cfg.get("steam_real", "/usr/bin/steam")).expanduser().resolve()
        blocked = [self.home / ".local/lib/uu-accelerator/steam", self.portable / "uu-network-steam", self.felix / "local-beta.py"]
        if steam in [p.resolve() for p in blocked]:
            raise Refused("Steam 实际入口不能回指 UU 或测试启动器。")
        return cfg

    def check(self):
        self.verify_layout()
        if not self.marker.is_file() or self.marker.read_text().strip() != OWNER:
            raise Refused("请先运行 install 创建测试版独立入口。")
        if not self.network_config.is_file() or b"netns=1" not in self.network_config.read_bytes().split(b"\n"):
            raise Refused("测试版前缀尚未启用独立网络。")
        cfg = self.read_config()
        for key in ("wrapper", "steam_real", "desktop_wrapper"):
            if key in cfg and not os.access(Path(cfg[key]).expanduser(), os.X_OK):
                raise Refused(f"个人配置中的 {key} 不可执行。")
        if "pasta_bin_dir" in cfg:
            pasta_ok = os.access(Path(cfg["pasta_bin_dir"]).expanduser() / "pasta", os.X_OK)
        else:
            pasta_ok = bool(shutil.which("pasta"))
        if not pasta_ok:
            raise Refused("未找到可用的 pasta。")
        state = session_state(self)
        state["client_installed"] = Path(cfg.get("uu_executable", str(self.client))).expanduser().is_file()
        state["version"] = VERSION
        state["prefix"] = str(self.prefix)
        return state

    def launch(self, mode, args):
        state = self.check()
        if state["conflict"]:
            raise Refused(state["conflict"], state["reason"])
        if mode == "steam" and not (state["beta_uu"] and state["beta_network"]):
            raise Refused("请先打开测试版 UU 并选好加速目标，再打开测试版 Steam。", "wrong-network")
        if mode == "setup" and state["beta_uu"]:
            raise Refused("测试版 UU 正在运行，请先正常退出再安装。")
        action = "setup" if mode == "setup" or (mode == "uu" and not state["client_installed"]) else mode
        extra = []
        if action == "setup":
            installer = Path(args.installer).expanduser().resolve() if getattr(args, "installer", None) else self.installer
            if not installer.is_file():
                raise Refused("找不到安装包。请下载官方 Windows 安装包后运行 setup --installer 路径。")
            with installer.open("rb") as stream:
                if stream.read(2) != b"MZ":
                    raise Refused("所选文件不是 Windows 安装程序。")
            unattended = bool(getattr(args, "unattended", False))
            if (unattended or not getattr(args, "installer", None)) and digest(installer.read_bytes()) != SETUP_SHA256:
                if unattended:
                    raise Refused("无人值守安装仅支持已验证的 UU 6.21.1.73 安装包。")
                raise Refused("默认安装包与已验证版本不同。请核实来源后使用 setup --installer 明确选取。")
            extra = [str(installer)]
            if unattended:
                extra.extend(["/silent", "/install_path", r"C:\Program Files (x86)\Netease\UU", "/no_launch_uu"])
        elif action == "steam":
            extra = getattr(args, "arguments", [])
        command = self.portable / ("uu-network-steam" if action == "steam" else "uu-network-launch")
        env = dict(os.environ)
        for key in CONFIG_OVERRIDES:
            env.pop(key, None)
        env["UU_NETWORK_CONFIG"] = str(self.config)
        if action != "steam":
            env.update(PROTON_USE_XALIA="0", PROTON_USE_WOW64="1", PROTON_NO_FSYNC="1", PROTON_DESKTOP_IMPORT="0")
        argv = [sys.executable, str(self.observer), "exec", "--prefix", str(self.prefix),
                "--action", action, "--", str(command), *extra]
        os.execve(sys.executable, argv, env)

    def mark_refusal(self, reason):
        if self.observer.is_file():
            try:
                subprocess.run([sys.executable, str(self.observer), "mark", "--prefix", str(self.prefix),
                                "--event", "launch-refused", "--reason", reason], stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=False)
            except (OSError, subprocess.TimeoutExpired):
                pass

    def mark_issue(self):
        try:
            result = subprocess.run([sys.executable, str(self.observer), "mark", "--prefix", str(self.prefix),
                                     "--event", "issue"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=4, check=False)
            message = "已标记刚才的异常。" if result.returncode == 0 else "当前没有可标记的观察记录。"
        except (OSError, subprocess.TimeoutExpired):
            message = "暂时无法标记，请稍后重试。"
        print(message)
        desktop_notice(message)


def desktop_notice(message):
    try:
        subprocess.run(["notify-send", "Felix UU 测试版", message], timeout=3, check=False,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        pass


def keeper(prefix, proc=Path("/proc"), runtime=None):
    uid = os.getuid()
    runtime = runtime or Path(os.environ.get("XDG_RUNTIME_DIR", "") or f"/tmp/shorin-proton-wrapper-{uid}")
    session = runtime / "shorin-proton-wrapper/sessions" / digest(str(prefix.resolve()).encode())[:16]
    try:
        text = (session / "keeper.pid").read_text().strip()
        if not text.isascii() or not text.isdecimal():
            raise Refused("无法确认测试会话状态，请稍后重试。", "wrong-network")
        p = proc / text
        if p.stat().st_uid != uid:
            raise Refused("会话进程不属于当前用户。", "wrong-network")
        cmd = (p / "cmdline").read_bytes().rstrip(b"\0").split(b"\0")
        ns = os.readlink(p / "ns/net")
        if len(cmd) != 3 or cmd[1] != b"-" or cmd[2] != os.fsencode(session):
            return None  # A stale keeper PID was reused by an unrelated process.
        if ns != (session / "netns").read_text().strip() or os.readlink(p / "ns/user") != (session / "userns").read_text().strip():
            raise Refused("网络会话正在变更，请稍后重试。", "wrong-network")
        return ns
    except FileNotFoundError:
        return None
    except PermissionError as exc:
        raise Refused("无法读取当前网络会话状态。", "wrong-network") from exc


def prefix_of(p):
    for item in (p / "environ").read_bytes().split(b"\0"):
        if item.startswith(b"WINEPREFIX="):
            return Path(os.fsdecode(item.partition(b"=")[2])).resolve()
    return None


def server_for(p, prefix):
    try:
        st = (prefix / "pfx").stat()
        cwd = Path(os.readlink(p / "cwd"))
    except FileNotFoundError:
        return False
    return (cwd.name == f"server-{st.st_dev:x}-{st.st_ino:x}" and
            cwd.parent.name.startswith(".wine-") and str(cwd.parent.parent) == "/tmp")


def has_beta_image(p, image, beta):
    root = beta.root.resolve()
    if str(image).startswith("/run/host/"):
        image = Path("/") / str(image).removeprefix("/run/host/")
    if image.is_relative_to(root):
        return True
    loader_names = {"wine", "wine64", "wine-preloader", "wine64-preloader", "wineserver", "wineserver64"}
    if image.name in loader_names:
        if image.is_relative_to(root.parent):
            return False  # Explicitly a different installed runner.
        candidates = [root / "files/bin" / image.name]
        candidates.extend(root / "files/lib/wine" / arch / image.name for arch in ("x86_64-unix", "i386-unix"))
        return any(c.is_file() and (p / "exe").samefile(c) for c in candidates)
    # Some exec/binfmt configurations expose the PE itself. Accept that case
    # only for a private-prefix image with ntdll mapped from the chosen runner.
    if image.is_relative_to((beta.prefix / "pfx").resolve()):
        with (p / "maps").open("rb") as mappings:
            for line in mappings:
                fields = line.rstrip(b"\n").split(None, 5)
                if len(fields) == 6:
                    mapped = Path(os.fsdecode(fields[5]).removesuffix(" (deleted)"))
                    if mapped.name in ("ntdll.so", "ntdll.dll"):
                        if str(mapped).startswith("/run/host/"):
                            mapped = Path("/") / str(mapped).removeprefix("/run/host/")
                        if mapped.is_relative_to(root):
                            return True
    return False


def session_state(beta, proc=Path("/proc"), runtime=None):
    """Inspect existing processes only. Do not invoke the namespace launcher."""
    wanted = keeper(beta.prefix, proc, runtime)
    old_ns = keeper(beta.stable, proc, runtime)
    conflict = "稳定版 UU 网络仍在使用，请正常退出稳定版 UU 和 Steam 后重试。" if old_ns else None
    reason = "wrong-network" if old_ns else None
    beta_uu, steam = False, 0
    for p in proc.iterdir():
        if not p.name.isascii() or not p.name.isdecimal():
            continue
        try:
            if p.stat().st_uid != os.getuid():
                continue
            comm = (p / "comm").read_bytes().rstrip(b"\n").lower()
            if comm not in (b"uu.exe", b"uu_launcher.exe", b"wineserver", b"wineserver64", b"steam"):
                continue
            image = Path(os.readlink(p / "exe").removesuffix(" (deleted)"))
            if comm == b"steam":
                if image.name == "steam":
                    steam += 1
                    if not wanted or os.readlink(p / "ns/net") != wanted:
                        conflict = "已有 Steam 使用其他网络。请在 Steam 菜单中正常退出，再打开测试版。"
                        reason = "wrong-network"
                continue
            prefix = prefix_of(p)
            if comm.startswith(b"wineserver"):
                if prefix == (beta.stable / "pfx").resolve() or server_for(p, beta.stable):
                    conflict, reason = "稳定版 UU 前缀仍在使用，请正常退出后重试。", "mixed-runner"
                    continue
                if prefix != (beta.prefix / "pfx").resolve() and not server_for(p, beta.prefix):
                    continue
            if not has_beta_image(p, image, beta) or (not comm.startswith(b"wineserver") and prefix != (beta.prefix / "pfx").resolve()):
                conflict, reason = "检测到其他版本的 UU 或运行器，请正常退出后重试。", "mixed-runner"
            elif not wanted or os.readlink(p / "ns/net") != wanted:
                conflict, reason = "测试前缀中的程序处于其他网络，请正常退出后重试。", "wrong-network"
            elif comm == b"uu.exe":
                beta_uu = True
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError as exc:
            raise Refused("无法确认当前进程的网络归属，请稍后重试。", "wrong-network") from exc
    return {"beta_network": wanted, "beta_uu": beta_uu, "native_steam_count": steam,
            "conflict": conflict, "reason": reason}


def main():
    parser = argparse.ArgumentParser(description="Felix UU 测试版")
    subs = parser.add_subparsers(dest="mode", required=True)
    for name in ("install", "uninstall", "uu", "mark"):
        subs.add_parser(name)
    subs.add_parser("check").add_argument("--json", action="store_true")
    setup = subs.add_parser("setup")
    setup.add_argument("--installer", help="已核实来源的 Windows 安装包")
    setup.add_argument("--unattended", action="store_true", help="使用已验证的 UU 6.21.1.73 静默安装至测试前缀")
    subs.add_parser("steam").add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    beta = Beta()
    try:
        if args.mode == "install":
            print(beta.install())
        elif args.mode == "uninstall":
            print(beta.uninstall())
        elif args.mode == "mark":
            beta.mark_issue()
        elif args.mode == "check":
            state = beta.check()
            if args.json:
                print(json.dumps(state, ensure_ascii=False))
            else:
                print("测试版 " + VERSION, "UU 已安装" if state["client_installed"] else "等待安装 UU",
                      state["conflict"] or ("测试版 UU 运行中" if state["beta_uu"] else "可以启动"), sep=" · ")
            return 2 if state["conflict"] else 0
        else:
            beta.launch(args.mode, args)
        return 0
    except (Refused, OSError, ValueError) as exc:
        message = str(exc) if isinstance(exc, Refused) else "操作未完成，请检查测试版文件与权限。"
        if args.mode in ("uu", "steam", "setup"):
            beta.mark_refusal(getattr(exc, "reason", "prepare"))
            desktop_notice(message)
        if args.mode == "check" and args.json:
            print(json.dumps({"version": VERSION, "error": message}, ensure_ascii=False))
        else:
            print(message, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
