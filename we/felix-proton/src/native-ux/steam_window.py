# SPDX-License-Identifier: BSD-3-Clause
"""Present an identified Steam client window for a normal no-argument click."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time


# Exact SignIn_Title values from the installed Steam UI language resources.
_LOGIN = frozenset(x.casefold() for x in (
    "تسجيل الدخول إلى Steam", "Iniciar a sessão no Steam", "Вписване в Steam",
    "Přihlášení do služby Steam", "Log på Steam", "Aanmelden bij Steam",
    "Sign in to Steam", "Kirjaudu Steamiin", "Se connecter à Steam", "Bei Steam anmelden",
    "Σύνδεση στο Steam", "Bejelentkezés a Steambe", "Login ke Steam", "Accedi a Steam",
    "Steamにサインイン", "Steam 로그인", "Iniciar sesión en Steam", "Daftar masuk ke Steam",
    "Logg inn på Steam", "Zaloguj się do Steam", "Iniciar sessão no Steam",
    "Conectează-te la Steam", "Войти в Steam", "登录蒸汽平台", "登录 Steam", "Logga in på Steam",
    "登入 Steam", "เข้าสู่ระบบ Steam", "Steam'e Giriş Yap", "Вхід до Steam", "Đăng nhập vào Steam",
))


def _run(argv):
    env = dict(os.environ, LC_ALL="C.UTF-8")
    p = subprocess.run(argv, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                       stderr=subprocess.DEVNULL, timeout=1, check=False)
    return p.stdout.decode("utf-8", "replace") if p.returncode == 0 else None


def _identity(pid, netns, proc=Path("/proc")):
    """Return native client identity or its primary browser process identity."""
    p = proc / str(pid)
    try:
        image = Path(os.readlink(p / "exe").removesuffix(" (deleted)"))
        name = (p / "comm").read_bytes().rstrip(b"\n")
        if p.stat().st_uid != os.getuid() or os.readlink(p / "ns/net") != netns:
            return None
        cmd = (p / "cmdline").read_bytes().split(b"\0")
        if name == b"steam" and image.name == "steam":
            if any(arg.startswith(b"-child-") or arg.startswith(b"--type=") for arg in cmd):
                return None
        elif name == b"steamwebhelper" and image.name == "steamwebhelper":
            if any(arg.startswith(b"--type=") for arg in cmd):
                return None
            owners = [arg[10:] for arg in cmd if arg.startswith(b"-steampid=")]
            if len(owners) != 1 or not owners[0].isdigit():
                return None
            owner = proc / owners[0].decode("ascii")
            if (owner.stat().st_uid != os.getuid() or os.readlink(owner / "ns/net") != netns or
                    (owner / "comm").read_bytes().rstrip(b"\n") != b"steam" or
                    Path(os.readlink(owner / "exe").removesuffix(" (deleted)")).name != "steam"):
                return None
        else:
            return None
        return name, (p / "stat").read_bytes().rsplit(b")", 1)[1].split()[19]
    except (OSError, IndexError, ValueError):
        return None


def _candidates(wmctrl, xprop, netns):
    windows = []
    for line in (_run([wmctrl, "-lpx"]) or "").splitlines():
        fields = line.split(None, 5)
        if len(fields) != 6:
            continue
        xid, _, pid, cls, _, title = fields
        if (not re.fullmatch(r"0x[0-9a-fA-F]{1,8}", xid) or not pid.isascii() or not pid.isdecimal() or
                cls.casefold() not in ("steam.steam", "steamwebhelper.steam")):
            continue
        title = title.strip().casefold()
        login = title in _LOGIN
        if not login and title != "steam":
            continue
        identity = _identity(int(pid), netns)
        if identity is None:
            continue
        props = _run([xprop, "-id", xid, "-notype", "_NET_WM_PID", "_NET_WM_WINDOW_TYPE", "WM_TRANSIENT_FOR"]) or ""
        if not re.search(rf"^_NET_WM_PID = {int(pid)}$", props, re.M):
            continue
        kinds = re.findall(r"_NET_WM_WINDOW_TYPE_[A-Z_]+", props)
        if not kinds or kinds[0] not in (("_NET_WM_WINDOW_TYPE_NORMAL", "_NET_WM_WINDOW_TYPE_DIALOG")
                                         if login else ("_NET_WM_WINDOW_TYPE_NORMAL",)):
            continue
        transient = re.search(r"^WM_TRANSIENT_FOR[^\n]*?\b(0x[0-9a-fA-F]+)", props, re.M)
        if not login and transient and int(transient[1], 16):
            continue
        windows.append((int(login), xid, int(pid), identity))
    return windows


def _active(xprop, xid):
    prop = _run([xprop, "-root", "-notype", "_NET_ACTIVE_WINDOW"]) or ""
    match = re.fullmatch(r"_NET_ACTIVE_WINDOW[^\n]*?\b(0x[0-9a-fA-F]+)\s*", prop)
    return bool(match and int(match[1], 16) == int(xid, 16))


def activate_existing(netns: str) -> bool:
    if not re.fullmatch(r"net:\[[0-9]+\]", netns or "") or not os.environ.get("DISPLAY"):
        return False
    wmctrl, xprop = shutil.which("wmctrl"), shutil.which("xprop")
    if not wmctrl or not xprop:
        return False
    try:
        windows = _candidates(wmctrl, xprop, netns)
        preferred = [w for w in windows if w[0]] or windows
        if len(preferred) != 1:
            return False
        _, xid, pid, identity = preferred[0]
        if _active(xprop, xid):
            return True
        if _identity(pid, netns) != identity or preferred[0] not in _candidates(wmctrl, xprop, netns):
            return False
        if _run([wmctrl, "-i", "-a", xid]) is None:
            return False
        for _ in range(5):
            if _active(xprop, xid):
                return True
            time.sleep(0.045)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    return False


def main(argv):
    if len(argv) < 2 or not re.fullmatch(r"net:\[[0-9]+\]", argv[0]):
        return 2
    fallback = Path(argv[1])
    if not fallback.is_absolute() or fallback.name != "uu-network-steam":
        return 2
    if activate_existing(argv[0]):
        return 0
    try:
        os.execv(str(fallback), argv[1:])
    except OSError:
        print("无法调用 Steam 网络启动器。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
