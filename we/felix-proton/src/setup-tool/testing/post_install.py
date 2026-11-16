#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Assertions after a real, account-free installation in the isolated case."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def verify(case, command, env, steam_before):
    from isolated_prefix import write
    sys.path.insert(0, "/opt/felix-source/native-ux")
    import routes
    from policy import Policy
    ctx = routes.load()
    config = json.loads(ctx.config.read_text())
    data = Path(env["XDG_DATA_HOME"])
    state = Path(env["XDG_STATE_HOME"])
    apps = data / "applications"
    original = {p: p.read_bytes() for p in (ctx.config, routes.active_file(),
                apps / "steam.desktop", apps / "uu-accelerator.desktop")}
    report = {"source": "Real setup CLI; synthetic Steam executable, official offline UU installer",
              "official_client_installed": ctx.client.is_file(), "steps": {}}

    def save():
        write(case / "post-install-result.json", report)

    def cli(action):
        result = subprocess.run(command[:3] + [action, "--json"], env=env,
                                capture_output=True, text=True, timeout=30)
        (case / ("setup-" + action + ".log")).write_text(result.stdout + result.stderr)
        assert result.returncode == 0, (action, result.stderr)
        return json.loads(result.stdout)

    save()
    assert report["official_client_installed"]
    steam_text = (apps / "steam.desktop").read_text()
    uu_text = (apps / "uu-accelerator.desktop").read_text()
    assert "\nIcon=steam\n" in steam_text and "%U" in steam_text
    icon = next(line[5:] for line in uu_text.splitlines() if line.startswith("Icon="))
    assert icon != "network-vpn" and Path(icon).is_file(), "UU brand icon absent"
    assert Path(icon).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    report["steps"]["original_steam_icon_and_uri_preserved"] = True
    report["steps"]["real_uu_icon_present"] = {"sha256": hashlib.sha256(Path(icon).read_bytes()).hexdigest()}
    report["status"] = cli("status")
    report["steps"]["status_exit_zero"] = True
    save()

    repeated = subprocess.run(command, env=env, capture_output=True, text=True, timeout=45)
    (case / "setup-repeated.log").write_text(repeated.stdout + repeated.stderr)
    assert repeated.returncode == 0, repeated.stderr
    assert all(p.read_bytes() == value for p, value in original.items())
    report["steps"]["repeat_keeps_config_active_and_entries_exact"] = True
    save()

    native = case / "native-network.py"
    native.write_text("import json,os,pathlib,time\npathlib.Path(" + repr(str(case / "native-network.json")) +
        ").write_text(json.dumps({'uid':os.getuid(),'network':os.readlink('/proc/self/ns/net')}))\n"
        "deadline=time.monotonic()+40\nwhile not pathlib.Path(" + repr(str(case / "native-stop")) +
        ").exists() and time.monotonic()<deadline:time.sleep(.1)\n")
    native_log = (case / "native-network.log").open("w")
    native_process = subprocess.Popen([config["wrapper"], "--prefix", str(ctx.prefix), "--runner", config["runner"],
        "/usr/bin/python3", "-B", str(native)], env=env, stdout=native_log, stderr=subprocess.STDOUT)
    deadline = time.monotonic() + 15
    while not (case / "native-network.json").exists() and time.monotonic() < deadline:
        assert native_process.poll() is None, "Native fixture launch failed"
        time.sleep(.1)
    assert (case / "native-network.json").is_file(), "Native fixture readiness timeout"
    key = hashlib.sha256(os.fsencode(ctx.prefix.resolve())).hexdigest()[:16]
    session = Path(env["XDG_RUNTIME_DIR"]) / "shorin-proton-wrapper/sessions" / key
    keeper = int((session / "keeper.pid").read_text())
    expected = (session / "netns").read_text().strip()
    native_result = json.loads((case / "native-network.json").read_text())
    assert native_result["network"] == expected and native_result["uid"] == os.getuid()
    assert expected != os.readlink("/proc/self/ns/net")
    report["steps"]["native_fixture_joins_same_prefix_keeper_network"] = native_result
    save()

    descriptors = [os.open(f"/proc/{keeper}/ns/{name}", os.O_RDONLY) for name in ("user", "net")]
    try:
        ledger = case / "cm-policy.json"
        with Policy(*descriptors, ledger) as policy:
            before = policy._tables()
            policy.capture_baseline()
            policy.reconcile([("203.0.113.80", 27017)])
            record = json.loads(ledger.read_text())
            baseline = record["baseline"]["dev"]
            policy._ip("link", "add", "UU-test", "type", "dummy")
            policy._ip("addr", "add", "198.18.0.2/24", "dev", "UU-test")
            policy._ip("link", "set", "UU-test", "up")
            policy._ip("route", "add", "203.0.113.80/32", "dev", "UU-test", "src", "198.18.0.2")
            def dev(protocol, port):
                return policy._ip("-4", "route", "get", "203.0.113.80", "ipproto", protocol,
                                  "dport", port, read=True)[0]["dev"]
            observed = {"protected_tcp": dev("tcp", 27017), "other_tcp": dev("tcp", 27018),
                        "same_port_udp": dev("udp", 27017)}
            assert observed == {"protected_tcp": baseline, "other_tcp": "UU-test", "same_port_udp": "UU-test"}
            policy._ip("link", "del", "UU-test")
            policy.rollback()
            assert not ledger.exists() and policy._tables() == before
        report["steps"]["exact_synthetic_cm_tcp_selectivity_and_rollback"] = observed
    finally:
        for fd in descriptors:
            os.close(fd)
        (case / "native-stop").touch()
        native_process.wait(timeout=10)
        native_log.close()
    save()

    # Run the packaged backend in its own interpreter to avoid module collisions.
    script = ("import json,sys;sys.path.insert(0,'/opt/felix-source/pairing-tool');"
              "from backend import PairingService;service=PairingService();"
              "before=service.inspect();assert before['ready'] and before['connected'],before;"
              "paired=service.pair('steam.desktop','uu-accelerator.desktop');"
              "after=service.inspect();assert after['managed'] and after['adopted'],after;"
              "service.remove();end=service.inspect();assert end['connected'] and not end['managed'],end;"
              "print(json.dumps({'before':before,'after':after,'end':end},ensure_ascii=False))")
    result = subprocess.run([sys.executable, "-B", "-c", script], env=env, capture_output=True, text=True, timeout=15)
    (case / "pairing-backend.log").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stderr
    assert all(p.read_bytes() == value for p, value in original.items())
    report["steps"]["real_pairing_backend_adopt_remove_preserves_entries"] = True
    save()

    # Capture only the private X server before restoring launchers.
    result = subprocess.run([sys.executable, "-B", "-c",
        "from PIL import ImageGrab;ImageGrab.grab(xdisplay=" + repr(env["DISPLAY"]) +
        ").save(" + repr(str(case / "installed-client-private.png")) + ")"], env=env,
        capture_output=True, text=True, timeout=15)
    report["steps"]["private_screenshot_saved"] = result.returncode == 0
    cli("restore")
    assert (apps / "steam.desktop").read_bytes() == steam_before
    assert not (apps / "uu-accelerator.desktop").exists()
    assert ctx.config.read_bytes() == original[ctx.config]
    assert ctx.client.is_file()
    report["steps"]["restore_preserves_prefix_config_and_original_steam"] = True
    report["passed"] = True
    report["finished_monotonic_ns"] = time.monotonic_ns()
    save()
    return report
