# SPDX-License-Identifier: BSD-3-Clause
"""Launch the accelerator and native Steam in the same verified session."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time


_OVERRIDES = ("UU_NETWORK_CONFIG", "UU_PREFIX", "UU_RUNNER", "UU_WRAPPER",
              "UU_EXE", "UU_PASTA_BIN_DIR", "UU_LOCALE", "UU_DESKTOP_WRAPPER", "STEAM_REAL")
_NAMESPACE = re.compile(r"net:\[[0-9]+\]")
_TIMEOUT = {"setup": 600, "uu": 120, "steam": 120}
_POLL = 0.75
_EXIT_GRACE = 3


class _Refusal(RuntimeError):
    def __init__(self, message, reason="prepare"):
        super().__init__(message)
        self.reason = reason


def _state(beta):
    try:
        state = beta.check()
    except RuntimeError:
        raise
    except Exception as error:
        if hasattr(error, "reason"):
            raise _Refusal(str(error), error.reason) from error
        raise RuntimeError("无法读取测试版状态，请检查程序和网络配置。") from error
    if state["conflict"]:
        if state.get("reason") == "wrong-network" and state["native_steam_count"]:
            raise _Refusal("Steam 已在其他网络中运行。请先在 Steam 菜单正常退出，再打开 UU 与 Steam。", "wrong-network")
        raise _Refusal(state["conflict"], state.get("reason") or "prepare")
    return state


def _uu_ready(state):
    return bool(state["beta_uu"] and _NAMESPACE.fullmatch(state["beta_network"] or ""))


def _observed_command(beta, action, extra):
    name = "uu-network-steam" if action == "steam" else "uu-network-launch"
    return [sys.executable, str(beta.observer), "exec", "--prefix", str(beta.prefix),
            "--action", action, "--", str(beta.portable / name), *extra]


def _ticket(beta, action):
    return Path(beta.config).parent / f".pair-starting-{action}.json"


def _process_identity(pid):
    """Linux process start ticks prevent treating a recycled PID as this launch."""
    proc = Path("/proc") / str(pid)
    try:
        if proc.stat().st_uid != os.getuid():
            return None
        stat = (proc / "stat").read_bytes().rsplit(b")", 1)[1].split()
        if stat[0] == b"Z":
            return None
        return int(stat[19])
    except (FileNotFoundError, ProcessLookupError):
        return None


def _pending(beta, action):
    ticket = _ticket(beta, action)
    if ticket.is_symlink():
        raise RuntimeError("启动记录是符号链接，请检查测试版配置目录。")
    try:
        record = json.loads(ticket.read_text(encoding="ascii"))
    except FileNotFoundError:
        return None
    if not isinstance(record, list) or len(record) != 2 or any(type(n) is not int or n <= 0 for n in record):
        raise RuntimeError("启动记录无效，请检查测试版配置目录后重试。")
    pid, ticks = record
    if _process_identity(pid) == ticks:
        # Confirm the exact action and prefix as well, including across reboots.
        expected = [os.fsencode(arg) for arg in _observed_command(beta, action, [])][1:]
        try:
            argv = (Path("/proc") / str(pid) / "cmdline").read_bytes().split(b"\0")
        except (FileNotFoundError, ProcessLookupError):
            argv = []
        if argv[1:len(expected) + 1] == expected:
            return pid, ticks
    ticket.unlink(missing_ok=True)
    return None


def _begin(beta, action, extra):
    existing = _pending(beta, action)
    if existing:
        return None, existing
    env = dict(os.environ)
    for name in _OVERRIDES:
        env.pop(name, None)
    env["UU_NETWORK_CONFIG"] = str(beta.config)
    if action in ("uu", "setup"):
        env.update(PROTON_USE_XALIA="0", PROTON_USE_WOW64="1",
                   PROTON_NO_FSYNC="1", PROTON_DESKTOP_IMPORT="0")
    ticket = _ticket(beta, action)
    # The portal serializes launch_pair calls. Stage the private receipt first
    # so an unwritable directory is reported before starting an application.
    fd, temporary = tempfile.mkstemp(prefix=".pair-", dir=ticket.parent)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            process = subprocess.Popen(_observed_command(beta, action, extra), env=env,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, start_new_session=True)
            # A confirmed client can outlive the portal. Reap its observer
            # while this process exists, without blocking the GUI or its exit.
            threading.Thread(target=process.wait, name=f"felix-reap-{action}", daemon=True).start()
            ticks = _process_identity(process.pid)
            if ticks is None:
                return process, None
            json.dump([process.pid, ticks], stream)
        os.replace(temporary, ticket)
        return process, (process.pid, ticks)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _wait(beta, action, process, identity, network=None):
    deadline = time.monotonic() + _TIMEOUT[action]
    ended = None
    ticket = _ticket(beta, action)
    while True:
        state = _state(beta)
        if action == "steam" and (not _uu_ready(state) or state["beta_network"] != network):
            raise RuntimeError("等待 Steam 时 UU 网络已变化，请重新打开入口。")
        rc = process.poll() if process is not None else None
        exited = rc is not None if process is not None else _process_identity(identity[0]) != identity[1]
        if action == "setup":
            # Wrapper exit 9 accompanied a completed install on the reference
            # machine. File existence only lets us proceed to real UU validation.
            ready = state["client_installed"] and (_uu_ready(state) or (exited and rc in (None, 0, 9)))
        elif action == "uu":
            ready = _uu_ready(state)
        else:
            ready = state["native_steam_count"] > 0
        if ready:
            ticket.unlink(missing_ok=True)
            return state
        now = time.monotonic()
        if exited:
            ended = now if ended is None else ended
            if now - ended >= _EXIT_GRACE:
                ticket.unlink(missing_ok=True)
                code = f"（退出码 {rc}）" if rc is not None else ""
                labels = {"setup": "安装程序已关闭，尚未确认 UU 安装完成",
                          "uu": "UU 启动器已退出，尚未检测到目标网络中的 UU",
                          "steam": "Steam 启动器已退出，尚未检测到目标网络中的 Steam"}
                raise RuntimeError(f"{labels[action]}{code}。请重新打开入口重试。")
        if now >= deadline:
            labels = {"setup": "安装仍在进行，请完成安装后重新打开入口。",
                      "uu": "等待 UU 加入测试网络超时，请查看 UU 窗口后重试。",
                      "steam": "等待 Steam 加入测试网络超时，请查看更新或登录窗口后重试。"}
            raise RuntimeError(labels[action])
        time.sleep(_POLL)


def _installer_path(selected):
    path = Path(selected).expanduser().resolve()
    if not path.is_file():
        raise RuntimeError("找不到所选安装包，请重新选择官方 Windows 安装程序。")
    with path.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise RuntimeError("所选文件不是 Windows 安装程序。")
    return path


def launch_pair(beta, choose_installer, installer=None):
    """Called with the portal lock held. The chooser returns a Path or None."""
    try:
        state = _state(beta)
        setup = _pending(beta, "setup")
        if not setup and _uu_ready(state) and not state["client_installed"]:
            raise RuntimeError("UU 已运行，但配置的安装位置没有启动程序，请检查 UU 安装路径。")
        if setup or not state["client_installed"]:
            if setup:
                state = _wait(beta, "setup", None, setup)
            else:
                selected = installer if installer is not None else choose_installer()
                if not selected:
                    return "已取消选择安装包。需要安装时可重新打开入口。"
                selected = _installer_path(selected)
                state = _state(beta)  # The file chooser may have stayed open.
                if not state["client_installed"]:
                    if _uu_ready(state):
                        raise RuntimeError("选择安装包期间 UU 已启动，请检查安装路径后重试。")
                    process, identity = _begin(beta, "setup", [str(selected)])
                    state = _wait(beta, "setup", process, identity)
        if not _uu_ready(state):
            process, identity = _begin(beta, "uu", [])
            state = _wait(beta, "uu", process, identity)
        else:
            _ticket(beta, "uu").unlink(missing_ok=True)
        network = state["beta_network"]
        state = _state(beta)
        if not _uu_ready(state) or state["beta_network"] != network:
            raise RuntimeError("UU 网络在启动期间发生变化，请重新打开入口。")
        if not state["native_steam_count"]:
            process, identity = _begin(beta, "steam", [])
            _wait(beta, "steam", process, identity, network)
        else:
            _ticket(beta, "steam").unlink(missing_ok=True)
        return "UU 和 Steam 已在同一测试网络中运行。可在 UU 中选择游戏并开启加速。"
    except RuntimeError as error:
        if hasattr(beta, "mark_refusal"):
            beta.mark_refusal(getattr(error, "reason", "prepare"))
        raise
    except (OSError, ValueError) as error:
        if hasattr(beta, "mark_refusal"):
            beta.mark_refusal("prepare")
        raise RuntimeError("未能启动或读取测试版会话，请检查程序、安装包与配置目录权限。") from error
