#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Real pinned-runner startup in a private home, network, mount and bus.

The existing desktop and home contents are hidden. HOME keeps its original
value; a clean case directory is mounted at that path in the child namespace.
All writable files and private runtime reference locks remain in --case.
No Steam account, UU account, game, host input or external network is used.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
import sys
import time

HERE = Path(__file__).resolve()
EXPECTED_ARCHIVE = "320d1a9fce1bd4a885c6cc88c35db50411234c0e5f477e167e15460d09362fea"
TOOL = "felix-proton-uu-test-0.1.0-test.1"


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    Path(path).chmod(0o600)


def network_snapshot():
    return [subprocess.check_output(["/usr/sbin/ip", "-4", *args]).decode()
            for args in (("rule", "show"), ("route", "show", "table", "all"))]


def environment(case):
    return {"HOME": os.environ["HOME"], "USER": os.environ.get("USER", "test"),
            "LOGNAME": os.environ.get("LOGNAME", "test"), "PATH": "/usr/bin:/bin",
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
            "XDG_RUNTIME_DIR": str(case / "runtime"),
            "XDG_CONFIG_HOME": os.environ["HOME"] + "/.config",
            "XDG_DATA_HOME": os.environ["HOME"] + "/.local/share",
            "XDG_CACHE_HOME": os.environ["HOME"] + "/.cache",
            "XDG_STATE_HOME": os.environ["HOME"] + "/.local/state",
            "GSETTINGS_BACKEND": "memory", "GIO_USE_VFS": "local",
            "DBUS_SYSTEM_BUS_ADDRESS": "unix:path=" + str(case / "no-system-bus"),
            "PRESSURE_VESSEL_VARIABLE_DIR": str(case / "pv-var"),
            "PRESSURE_VESSEL_COPY_RUNTIME": "0", "PROTON_NO_ESYNC": "1",
            "LIBGL_ALWAYS_SOFTWARE": "1", "GALLIUM_DRIVER": "llvmpipe",
            "__GLX_VENDOR_LIBRARY_NAME": "mesa",
            "__EGL_VENDOR_LIBRARY_FILENAMES": "/usr/share/glvnd/egl_vendor.d/50_mesa.json"}


def outer(args):
    case = args.case.resolve()
    if case.exists():
        raise RuntimeError("Use a fresh, nonexistent case directory")
    assert digest(args.archive) == EXPECTED_ARCHIVE
    case.mkdir(mode=0o700)
    for name in ("home", "runtime", "tmp", "refs", "pv-var"):
        (case / name).mkdir(mode=0o700)
    (case / "tmp/.X11-unix").mkdir(mode=0o1777)
    shutil.copytree(HERE.parent, case / "testing", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    sources = case / "source"
    sources.mkdir(mode=0o700)
    for folder in ("native-ux", "setup-tool", "pairing-tool"):
        shutil.copytree(args.native_source.resolve().parent / folder, sources / folder,
                       ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    metadata = {"case": str(case), "home": os.environ["HOME"],
                "mode": args.mode, "graphical": args.graphical, "xvfb": bool(args.xvfb),
                "host_network_before": network_snapshot(),
                "host_namespaces": {key: os.readlink("/proc/self/ns/" + key)
                                    for key in ("user", "net", "mnt", "ipc", "uts")},
                "archive_sha256": digest(args.archive),
                "wrapper_sha256": digest(args.wrapper), "pasta_sha256": digest(args.pasta),
                "probe_sha256": digest(args.probe), "harness_sha256": digest(HERE),
                "source_files": {str(p.relative_to(sources)): digest(p)
                                 for p in sources.rglob("*") if p.is_file()}, "refs": []}
    for number, ref in enumerate(sorted(args.runtime.glob("*/files/.ref"))):
        assert ref.is_file() and not ref.is_symlink() and ref.stat().st_size == 0
        private = case / "refs" / str(number)
        private.touch(mode=0o600)
        metadata["refs"].append({"source": str(private),
                                 "dest": str(Path("/opt/felix-slr4") / ref.relative_to(args.runtime))})
    assert metadata["refs"], "SLR reference files missing"
    (case / "bus.conf").write_text('<busconfig><type>session</type><listen>unix:path=' +
        str(case / "runtime/bus") + '</listen><auth>EXTERNAL</auth><policy context="default">'
        '<allow user="' + str(os.getuid()) + '"/><allow own="*"/><allow send_destination="*"/>'
        '<allow receive_sender="*"/></policy></busconfig>\n')
    write(case / "case.json", metadata)
    command = ["unshare", "--user", "--map-current-user", "--keep-caps", "--net",
               sys.executable, "-B", str(case / "testing/isolated_prefix.py"), "_network", "--case", str(case),
               "--archive", str(args.archive.resolve()), "--wrapper", str(args.wrapper.resolve()),
               "--pasta", str(args.pasta.resolve()), "--runtime", str(args.runtime.resolve()),
               "--native-source", str(args.native_source.resolve()), "--probe", str(args.probe.resolve())]
    if args.uu_installer:
        command += ["--uu-installer", str(args.uu_installer.resolve())]
    if args.xvfb:
        metadata["xvfb_sha256"] = digest(args.xvfb)
        write(case / "case.json", metadata)
        command += ["--xvfb", str(args.xvfb.resolve())]
    with (case / "outer.log").open("w") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                   env=environment(case), start_new_session=True)
        try:
            result = process.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=8)
            result = 124
    metadata.update(exit=result, host_network_after=network_snapshot())
    metadata["host_network_unchanged"] = metadata["host_network_before"] == metadata["host_network_after"]
    write(case / "outer-result.json", metadata)
    print(json.dumps({"case": str(case), "exit": result,
                      "host_network_unchanged": metadata["host_network_unchanged"]}))
    assert metadata["host_network_unchanged"]
    return result


def network(args):
    subprocess.run(["/usr/sbin/ip", "link", "set", "lo", "up"], check=True)
    subprocess.run(["/usr/sbin/ip", "link", "add", "outer0", "type", "dummy"], check=True)
    subprocess.run(["/usr/sbin/ip", "addr", "add", "192.0.2.2/24", "dev", "outer0"], check=True)
    subprocess.run(["/usr/sbin/ip", "link", "set", "outer0", "up"], check=True)
    subprocess.run(["/usr/sbin/ip", "route", "add", "default", "via", "192.0.2.1", "dev", "outer0"], check=True)
    case = args.case.resolve()
    meta = json.loads((case / "case.json").read_text())
    command = ["bwrap", "--unshare-user", "--unshare-pid", "--unshare-ipc", "--unshare-uts", "--die-with-parent",
               "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
               "--tmpfs", "/run", "--tmpfs", "/opt", "--bind", str(case / "tmp"), "/tmp",
               "--bind", str(case), str(case), "--bind", str(case / "home"), meta["home"],
               "--dev-bind", "/dev/net/tun", "/dev/net/tun",
               "--ro-bind", str(args.archive), "/opt/felix-runner.tar.zst",
               "--ro-bind", str(case / "source"), "/opt/felix-source",
               "--ro-bind", str(HERE.parent), "/opt/felix-testing",
               "--ro-bind", str(args.wrapper), "/opt/felix-bin/shorin-proton-wrapper",
               "--ro-bind", str(args.pasta), "/opt/felix-bin/pasta",
               "--ro-bind", str(args.probe), "/opt/felix-probe.exe",
               "--ro-bind", str(args.runtime), "/opt/felix-slr4"]
    if args.uu_installer:
        command += ["--ro-bind", str(args.uu_installer), "/opt/felix-installer.exe"]
    if args.xvfb:
        command += ["--ro-bind", str(args.xvfb), "/opt/felix-xvfb"]
    for ref in meta["refs"]:
        command += ["--bind", ref["source"], ref["dest"]]
    command += ["--cap-drop", "ALL", "--", "dbus-run-session", "--config-file=" + str(case / "bus.conf"), "--", "/usr/bin/python3", "-B",
                "/opt/felix-testing/isolated_prefix.py", "_inside", "--case", str(case)]
    class Header(ctypes.Structure):
        _fields_ = [("version", ctypes.c_uint32), ("pid", ctypes.c_int)]
    class Data(ctypes.Structure):
        _fields_ = [("effective", ctypes.c_uint32), ("permitted", ctypes.c_uint32),
                    ("inheritable", ctypes.c_uint32)]
    libc = ctypes.CDLL(None, use_errno=True)
    header, data = Header(0x20080522, 0), (Data * 2)()
    if libc.capset(ctypes.byref(header), ctypes.byref(data)):
        raise OSError(ctypes.get_errno(), "capset")
    os.execvpe(command[0], command, environment(case))


def inside(args):
    case = args.case.resolve()
    meta = json.loads((case / "case.json").read_text())
    namespaces = {key: os.readlink("/proc/self/ns/" + key) for key in meta["host_namespaces"]}
    assert all(value != meta["host_namespaces"][key] for key, value in namespaces.items())
    assert os.environ["HOME"] == meta["home"] and Path.home() == Path(meta["home"])
    assert Path.home().stat().st_ino == (case / "home").stat().st_ino
    assert not (Path.home() / ".config/felix-native-ux/active.json").exists()
    assert not Path("/run/user/" + str(os.getuid()) + "/bus").exists()
    interfaces = list(Path("/proc/self/net/dev").read_text().splitlines()[2:])
    assert {line.split(":", 1)[0].strip() for line in interfaces} == {"lo", "outer0"}
    sys.path.insert(0, "/opt/felix-source/native-ux")
    import setup_config
    root = Path.home() / ".local/share/Steam"
    (root / "steamapps").mkdir(parents=True)
    (root / "steam.sh").write_text("#!/bin/sh\nexit 0\n")
    (root / "steam.sh").chmod(0o755)
    steam = Path.home() / "steam-fixture"
    steam.write_text("#!/bin/sh\nexit 0\n")
    steam.chmod(0o755)
    runtime = Path(os.environ["XDG_DATA_HOME"]) / "shorin-proton-wrapper/runtime"
    runtime.mkdir(parents=True)
    (runtime / "steamrt4").symlink_to("/opt/felix-slr4")
    env = dict(os.environ, PATH="/opt/felix-bin:/usr/bin:/bin",
               DBUS_SYSTEM_BUS_ADDRESS=os.environ["DBUS_SESSION_BUS_ADDRESS"])
    if meta["xvfb"]:
        authority = case / "runtime/Xauthority"
        authority.touch(mode=0o600)
        import secrets
        subprocess.run(["xauth", "-f", str(authority), "add", ":99", ".", secrets.token_hex(16)], check=True)
        env.update(DISPLAY=":99", XAUTHORITY=str(authority), XDG_SESSION_TYPE="x11")
        shell_log = (case / "xvfb.log").open("w")
        shell = subprocess.Popen(["/opt/felix-xvfb", ":99", "-screen", "0", "1280x720x24",
            "-nolisten", "tcp", "-noreset", "-auth", str(authority)],
            env=env, stdout=shell_log, stderr=subprocess.STDOUT, start_new_session=True)
        until = time.monotonic() + 15
        while time.monotonic() < until:
            if shell.poll() is not None:
                raise RuntimeError("Private Xvfb exited")
            result = subprocess.run(["xwininfo", "-root"], env=env, capture_output=True, timeout=2)
            if result.returncode == 0:
                break
            time.sleep(.1)
        else:
            raise RuntimeError("Private Xvfb readiness timeout")
        write(case / "private-gui-environment.json", {k: env[k] for k in
              ("DISPLAY", "XAUTHORITY", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")})
    elif meta["graphical"]:
        env.update(WAYLAND_DISPLAY="felix-fromzero-private", XDG_SESSION_TYPE="wayland",
                   XDG_CURRENT_DESKTOP="GNOME", GNOME_SHELL_SESSION_MODE="user")
        shell_log = (case / "gnome-shell.log").open("w")
        shell = subprocess.Popen(["gnome-shell", "--headless", "--wayland", "--mode=user",
            "--virtual-monitor=1280x720", "--wayland-display=" + env["WAYLAND_DISPLAY"]],
            env=env, stdout=shell_log, stderr=subprocess.STDOUT, start_new_session=True)
        until = time.monotonic() + 40
        while time.monotonic() < until:
            if shell.poll() is not None:
                raise RuntimeError("Private GNOME exited; inspect gnome-shell.log")
            display = re.search(r"Using public X11 display (:[0-9]+)", (case / "gnome-shell.log").read_text())
            authorities = list((case / "runtime").glob(".mutter-Xwaylandauth.*"))
            if display and len(authorities) == 1:
                env.update(DISPLAY=display.group(1), XAUTHORITY=str(authorities[0]))
                break
            time.sleep(.1)
        else:
            raise RuntimeError("Private GNOME readiness timeout")
        write(case / "private-gui-environment.json", {k: env[k] for k in
              ("DISPLAY", "XAUTHORITY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")})
    if meta["mode"] == "install":
        applications = Path(env["XDG_DATA_HOME"]) / "applications"
        applications.mkdir(parents=True)
        steam_before = b"[Desktop Entry]\nType=Application\nName=Steam\nExec=steam %U\nIcon=steam\nMimeType=x-scheme-handler/steam;\n"
        (applications / "steam.desktop").write_bytes(steam_before)
        command = [sys.executable, "-B", "/opt/felix-source/setup-tool/setup.py", "install",
                   "--runner-archive", "/opt/felix-runner.tar.zst", "--wrapper", "/opt/felix-bin/shorin-proton-wrapper",
                   "--pasta", "/opt/felix-bin/pasta", "--steam-root", str(root), "--steam", str(steam),
                   "--uu-installer", "/opt/felix-installer.exe", "--offline", "--json"]
        write(case / "setup-command.json", command)
        checked = subprocess.run(command[:3] + ["check"] + command[4:], env=env,
                                 capture_output=True, text=True, timeout=30)
        (case / "setup-check.log").write_text(checked.stdout + checked.stderr)
        assert checked.returncode == 0, checked.stderr
        assert not (Path.home() / "Games/Felix-UU-0.1.0-test.1").exists()
        with (case / "setup-install.log").open("w") as log:
            result = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=620)
        write(case / "inside-result.json", {"mode": "install", "exit": result.returncode,
              "scope": "Official UU installer, no account or game; synthetic native Steam entry",
              "source_files": meta["source_files"]})
        if result.returncode == 0:
            from post_install import verify
            verify(case, command, env, steam_before)
        return result.returncode
    config = setup_config.ensure_config(Path("/opt/felix-runner.tar.zst"),
        steam_root=root, wrapper="/opt/felix-bin/shorin-proton-wrapper", pasta="/opt/felix-bin/pasta", steam=steam)
    cfg = json.loads(config.read_text())
    assert not (Path(cfg["prefix"]) / "pfx").exists()
    wrapper = [cfg["wrapper"], "--prefix", cfg["prefix"], "--runner", cfg["runner"]]
    started = time.monotonic()
    with (case / "wineboot.log").open("w") as log:
        result = subprocess.run(wrapper + ["--init"], env=env, stdout=log,
                                stderr=subprocess.STDOUT, timeout=180)
    report = {"scope": "Pinned runner and new Windows prefix only; no real Steam or UU",
              "namespaces": namespaces, "home_hidden_by_clean_bind": True,
              "offline_dummy_network": True, "config_created": True,
              "runner_installed_from_pinned_archive": True, "wineboot_exit": result.returncode,
              "wineboot_seconds": round(time.monotonic() - started, 3),
              "private_display_exit_after_wineboot": shell.poll() if meta["graphical"] or meta["xvfb"] else None,
              "system_registry_created": (Path(cfg["prefix"]) / "pfx/system.reg").is_file()}
    write(case / "inside-result.json", report)
    assert result.returncode == 0 and report["system_registry_created"]
    probe_dir = Path(cfg["prefix"]) / "pfx/drive_c/felix-test"
    probe_dir.mkdir()
    executable = probe_dir / "prefix-probe.exe"
    shutil.copyfile("/opt/felix-probe.exe", executable)
    output = probe_dir / "result.json"
    with (case / "probe.log").open("w") as log:
        probe = subprocess.run(wrapper + [str(executable), "C:\\felix-test\\result.json"],
                               env=env, stdout=log, stderr=subprocess.STDOUT, timeout=90)
    report.update(probe_exit=probe.returncode, probe=json.loads(output.read_text()) if output.exists() else None)
    write(case / "inside-result.json", report)
    assert probe.returncode == 0 and report["probe"]["file_write"]
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("run", "_network", "_inside"))
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--wrapper", type=Path)
    parser.add_argument("--pasta", type=Path)
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--native-source", type=Path)
    parser.add_argument("--probe", type=Path)
    parser.add_argument("--timeout", type=int, default=360)
    parser.add_argument("--mode", choices=("prefix", "install"), default="prefix")
    parser.add_argument("--graphical", action="store_true")
    parser.add_argument("--uu-installer", type=Path)
    parser.add_argument("--xvfb", type=Path, help="Optional Xvfb executable; uses a private authenticated display")
    args = parser.parse_args()
    return {"run": outer, "_network": network, "_inside": inside}[args.phase](args)


if __name__ == "__main__":
    sys.excepthook = sys.__excepthook__
    raise SystemExit(main())
