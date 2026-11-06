# SPDX-License-Identifier: BSD-3-Clause
"""The subprocess integration fixture writes synthetic state, not real networks."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

import pair_session as pair


OBSERVER = '''import json, os, pathlib, sys, time
root = pathlib.Path(os.environ["UU_NETWORK_CONFIG"]).parent
args = sys.argv[1:]
action = args[args.index("--action") + 1]
state_path = root / "session.json"
state = json.loads(state_path.read_text())
scenario = os.environ.get("PAIR_FIXTURE", "")
keys = ["UU_NETWORK_CONFIG","UU_PREFIX","UU_RUNNER","STEAM_REAL","PROTON_NO_FSYNC",
        "PROTON_USE_WOW64","PROTON_USE_XALIA","PROTON_DESKTOP_IMPORT","WINEPREFIX","HOME"]
with (root / "calls.jsonl").open("a") as output:
    output.write(json.dumps({"action":action, "argv":args, "env":{k:os.environ.get(k) for k in keys}})+"\\n")
if action == "setup":
    if scenario == "cancel": sys.exit(0)
    if scenario == "unknown-exit": sys.exit(37)
    state["client_installed"] = True
    if scenario == "auto-uu":
        state.update(beta_uu=True,beta_network="net:[99]")
elif action == "uu":
    if scenario == "uu-fail": sys.exit(2)
    if scenario == "delayed-uu": time.sleep(0.45)
    state.update(beta_uu=True,beta_network="net:[99]")
    if scenario == "foreign-during-uu":
        state.update(native_steam_count=1, conflict="foreign client", reason="wrong-network")
elif action == "steam":
    if scenario == "steam-fail": sys.exit(2)
    state["native_steam_count"] = 1
tmp = state_path.with_suffix(".tmp")
tmp.write_text(json.dumps(state))
tmp.replace(state_path)
if action == "setup" and scenario == "setup-nine": sys.exit(9)
'''


class FixtureBeta:
    def __init__(self, root):
        self.root = root
        self.config = root / "config.json"
        self.config.write_text("{}")
        self.observer = root / "observe.py"
        self.observer.write_text(OBSERVER)
        self.prefix = root / "独立 prefix"
        self.portable = root / "launchers"
        self.record = root / "session.json"
        self.refusals = []
        self.record.write_text(json.dumps({"client_installed": True, "conflict": None, "reason": None,
                                          "beta_uu": False, "beta_network": None, "native_steam_count": 0}))

    def check(self):
        return json.loads(self.record.read_text())

    def put(self, **changes):
        self.record.write_text(json.dumps(self.check() | changes))

    def mark_refusal(self, reason):
        self.refusals.append(reason)

    def calls(self):
        p = self.root / "calls.jsonl"
        return [json.loads(s) for s in p.read_text().splitlines()] if p.exists() else []

    def actions(self):
        return [row["action"] for row in self.calls()]


class PairTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory(prefix="felix pair ")))
        self.beta = FixtureBeta(self.root)
        self.chooser = mock.Mock(return_value=None)
        self.enterContext(mock.patch.object(pair, "_POLL", 0.012))
        self.enterContext(mock.patch.object(pair, "_EXIT_GRACE", 0.055))
        self.enterContext(mock.patch.object(pair, "_TIMEOUT", {"uu": 2, "steam": 2, "setup": 2}))
        self.enterContext(mock.patch.dict(os.environ, {"PAIR_FIXTURE": ""}))

    def start(self, installer=None):
        return pair.launch_pair(self.beta, self.chooser, installer)

    def installer(self):
        path = self.root / "全新 Unknown UU setup.exe"
        path.write_bytes(b"MZfixture")
        return path

    def test_clean_pair_verified_preserves_environment_and_desktop_options(self):
        injected = {"UU_PREFIX": "/wrong/prefix", "UU_RUNNER": "/wrong/proton", "STEAM_REAL": "/wrong/steam",
                    "WINEPREFIX": "/per-game", "PROTON_NO_FSYNC": "custom"}
        with mock.patch.dict(os.environ, injected):
            self.assertIn("同一测试网络", self.start())
        self.assertEqual(self.beta.actions(), ["uu", "steam"])
        self.chooser.assert_not_called()
        uu, steam = self.beta.calls()
        for row in (uu, steam):
            self.assertEqual(row["argv"][:4], ["exec", "--prefix", str(self.beta.prefix), "--action"])
            self.assertEqual(row["env"]["UU_NETWORK_CONFIG"], str(self.beta.config))
            self.assertIsNone(row["env"]["UU_PREFIX"])
            self.assertIsNone(row["env"]["UU_RUNNER"])
            self.assertIsNone(row["env"]["STEAM_REAL"])
            self.assertEqual(row["env"]["HOME"], os.environ.get("HOME"))
        self.assertEqual(uu["argv"][-1], str(self.beta.portable / "uu-network-launch"))
        self.assertEqual(uu["env"]["PROTON_NO_FSYNC"], "1")
        self.assertEqual(uu["env"]["PROTON_DESKTOP_IMPORT"], "0")
        self.assertEqual(steam["argv"][-1], str(self.beta.portable / "uu-network-steam"))
        self.assertEqual(steam["env"]["PROTON_NO_FSYNC"], "custom")
        self.assertEqual(steam["env"]["WINEPREFIX"], "/per-game")
        self.assertFalse(list(self.root.glob(".pair-starting-*")))

    def test_both_ready_is_idempotent_with_no_route_or_game_selection(self):
        self.beta.put(beta_network="net:[99]", beta_uu=True, native_steam_count=1)
        self.assertIn("已在同一", self.start())
        self.assertEqual(self.beta.actions(), [])

    def test_ready_uu_only_launches_steam(self):
        self.beta.put(beta_network="net:[99]", beta_uu=True)
        self.start()
        self.assertEqual(self.beta.actions(), ["steam"])

    def test_foreign_steam_fails_before_launch_or_chooser(self):
        self.beta.put(client_installed=False, native_steam_count=1, conflict="foreign", reason="wrong-network")
        with self.assertRaisesRegex(RuntimeError, "正常退出"):
            self.start()
        self.chooser.assert_not_called()
        self.assertEqual(self.beta.actions(), [])
        self.assertEqual(self.beta.refusals, ["wrong-network"])

    def test_foreign_steam_appearing_during_uu_start_blocks_steam(self):
        with mock.patch.dict(os.environ, {"PAIR_FIXTURE":"foreign-during-uu"}), self.assertRaisesRegex(RuntimeError, "正常退出"):
            self.start()
        self.assertEqual(self.beta.actions(), ["uu"])

    def test_cancel_or_bad_installer_starts_nothing(self):
        self.beta.put(client_installed=False)
        self.assertIn("取消", self.start())
        invalid = self.root / "bad.exe"
        invalid.write_bytes(b"ELF")
        with self.assertRaisesRegex(RuntimeError, "Windows 安装程序"):
            self.start(invalid)
        self.assertEqual(self.beta.actions(), [])

    def test_unknown_installer_is_interactive_and_auto_launch_is_reused(self):
        self.beta.put(client_installed=False)
        self.chooser.return_value = self.installer()
        with mock.patch.dict(os.environ, {"PAIR_FIXTURE":"auto-uu"}):
            self.start()
        self.assertEqual(self.beta.actions(), ["setup","steam"])
        self.assertEqual(self.beta.calls()[0]["argv"][-2:], [str(self.beta.portable / "uu-network-launch"), str(self.chooser.return_value)])
        self.assertNotIn("/silent", self.beta.calls()[0]["argv"])

    def test_completed_install_exit_nine_still_requires_real_uu_and_steam(self):
        self.beta.put(client_installed=False)
        with mock.patch.dict(os.environ, {"PAIR_FIXTURE":"setup-nine"}):
            self.start(self.installer())
        self.assertEqual(self.beta.actions(), ["setup","uu","steam"])
        self.chooser.assert_not_called()

    def test_cancelled_installer_exits_without_launching_uu_or_steam(self):
        self.beta.put(client_installed=False)
        with mock.patch.dict(os.environ, {"PAIR_FIXTURE":"cancel"}), self.assertRaisesRegex(RuntimeError, "尚未确认"):
            self.start(self.installer())
        self.assertEqual(self.beta.actions(), ["setup"])
        self.assertFalse(list(self.root.glob(".pair-starting-*")))

    def test_failed_uu_does_not_launch_steam(self):
        with mock.patch.dict(os.environ, {"PAIR_FIXTURE":"uu-fail"}), self.assertRaisesRegex(RuntimeError, "退出码 2"):
            self.start()
        self.assertEqual(self.beta.actions(), ["uu"])

    def test_steam_exit_without_running_does_not_report_success(self):
        with mock.patch.dict(os.environ, {"PAIR_FIXTURE":"steam-fail"}), self.assertRaisesRegex(RuntimeError, "目标网络中的 Steam"):
            self.start()
        self.assertEqual(self.beta.actions(), ["uu","steam"])

    def test_timeout_retry_resumes_working_observer_without_duplicate_uu(self):
        with mock.patch.dict(os.environ, {"PAIR_FIXTURE":"delayed-uu"}):
            with mock.patch.dict(pair._TIMEOUT, {"uu":0.12}), self.assertRaisesRegex(RuntimeError, "超时"):
                self.start()
            self.assertTrue(pair._ticket(self.beta,"uu").exists())
            self.assertIn("同一测试网络", self.start())
        self.assertEqual(self.beta.actions(), ["uu","steam"])
        self.assertFalse(list(self.root.glob(".pair-starting-*")))

    def test_disappeared_pending_pid_does_not_block_retry(self):
        pair._ticket(self.beta, "uu").write_text("[99999999, 123]")
        self.start()
        self.assertEqual(self.beta.actions(), ["uu","steam"])


if __name__ == "__main__":
    unittest.main()
