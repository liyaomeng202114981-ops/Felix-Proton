# SPDX-License-Identifier: BSD-3-Clause
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import steam_window as window


NS = "net:[299]"


class SteamWindowTests(unittest.TestCase):
    def setUp(self):
        self.proc = Path(self.enterContext(tempfile.TemporaryDirectory()))
        for pid, comm, cmd in [(20,b"steam",[b"/client/steam"]),
                               (30,b"steamwebhelper",[b"/client/steamwebhelper",b"-steampid=20"])]:
            p=self.proc/str(pid)
            (p/"ns").mkdir(parents=True)
            (p/"ns/net").symlink_to(NS)
            (p/"comm").write_bytes(comm+b"\n")
            (p/"exe").symlink_to("/client/"+comm.decode())
            (p/"cmdline").write_bytes(b"\0".join(cmd)+b"\0")
            (p/"stat").write_bytes(str(pid).encode()+b" ("+comm+b") S "+b"0 "*18+b"123 0\n")
        self.listing="0x0700003b 0 30 steamwebhelper.steam fixture-host 登录 Steam\n"
        self.props="_NET_WM_PID = 30\n_NET_WM_WINDOW_TYPE = _NET_WM_WINDOW_TYPE_NORMAL\nWM_TRANSIENT_FOR: not found.\n"
        self.active=0x123
        self.activated=[]
        self.allow_focus=True
        self.enterContext(mock.patch.dict(os.environ,{"DISPLAY":":fixture"}))
        self.enterContext(mock.patch.object(window.shutil,"which",side_effect=lambda n:"/fixture/"+n))
        self.enterContext(mock.patch.object(window.time,"sleep"))
        self.enterContext(mock.patch.object(window,"_run",side_effect=self.run_cmd))
        real=window._identity
        self.enterContext(mock.patch.object(window,"_identity",side_effect=lambda pid, ns: real(pid,ns,self.proc)))

    def run_cmd(self, argv):
        if argv[1:]==["-lpx"]: return self.listing
        if argv[1]=="-id": return self.props
        if argv[1]=="-root": return "_NET_ACTIVE_WINDOW: window id # "+hex(self.active)+"\n"
        if argv[1:3]==["-i","-a"]:
            self.activated.append(argv[-1])
            if self.allow_focus:self.active=int(argv[-1],16)
            return ""
        raise AssertionError(argv)

    def test_only_identified_main_webhelper_login_becomes_active(self):
        self.assertTrue(window.activate_existing(NS))
        self.assertEqual(self.activated,["0x0700003b"])
        self.assertTrue(window.activate_existing(NS))
        self.assertEqual(len(self.activated),1)

    def test_exact_localized_login_titles_and_unknown_chat_offer_rejected(self):
        for title in ["Sign in to Steam","Se connecter à Steam","Steamにサインイン","Войти в Steam","登入 Steam"]:
            self.listing="0x0700003b 0 30 steamwebhelper.steam fixture-host "+title+"\n"
            self.assertTrue(window.activate_existing(NS),title)
        self.activated.clear()
        for title in ["Steam - News","Steam Chat","Sign in to Steam for free gifts","Messages","登录 Steam 领取奖励"]:
            self.listing="0x0700003b 0 30 steamwebhelper.steam fixture-host "+title+"\n"
            self.assertFalse(window.activate_existing(NS),title)
        self.assertEqual(self.activated,[])

    def test_main_native_and_reject_transient(self):
        self.listing="0x01000002 0 20 Steam.Steam fixture-host Steam\n"
        self.props=self.props.replace(" = 30"," = 20")
        self.assertTrue(window.activate_existing(NS))
        self.props=self.props.replace("WM_TRANSIENT_FOR: not found.","WM_TRANSIENT_FOR: window id # 0x000001ab")
        self.assertFalse(window.activate_existing(NS))

    def test_wrong_namespace_or_spoofed_client_class_rejected(self):
        self.assertFalse(window.activate_existing("net:[9999]"))
        self.listing=self.listing.replace("steamwebhelper.steam","myapp.steam")
        self.assertFalse(window.activate_existing(NS))
        self.assertEqual(self.activated,[])

    def test_browser_renderer_and_wrong_owner_namespace_rejected(self):
        p=self.proc/"30/cmdline"
        original=p.read_bytes()
        p.write_bytes(original+b"--type=renderer\0")
        self.assertFalse(window.activate_existing(NS))
        p.write_bytes(original)
        ns=self.proc/"20/ns/net"
        ns.unlink()
        ns.symlink_to("net:[other]")
        self.assertFalse(window.activate_existing(NS))
        self.assertEqual(self.activated,[])

    def test_property_pid_mismatch_or_auxiliary_window_type_rejected(self):
        before=self.props
        self.props=before.replace(" = 30"," = 70")
        self.assertFalse(window.activate_existing(NS))
        self.props=before.replace("_NORMAL","_UTILITY")
        self.assertFalse(window.activate_existing(NS))

    def test_ambiguous_or_disappearing_candidates_are_not_raised(self):
        self.listing+=self.listing.replace("0x0700003b","0x0700004c")
        self.assertFalse(window.activate_existing(NS))
        identity=(b"steamwebhelper",b"123")
        with mock.patch.object(window,"_candidates",side_effect=[[(1,"0x0700003b",30,identity)],[]]):
            self.assertFalse(window.activate_existing(NS))
        self.assertEqual(self.activated,[])

    def test_activation_denied_or_optional_tool_missing_calls_fallback(self):
        self.allow_focus=False
        args=[NS,"/fixture/uu-network-steam","steam://open/games","literal shell $sometimes"]
        with mock.patch.object(window.os,"execv") as execute:
            self.assertEqual(window.main(args),0)
            execute.assert_called_once_with(args[1],args[1:])
        with mock.patch.object(window.shutil,"which",return_value=None):
            self.assertFalse(window.activate_existing(NS))
        with mock.patch.object(window,"_run",side_effect=subprocess.TimeoutExpired("wmctrl",1)):
            self.assertFalse(window.activate_existing(NS))

    def test_success_returns_zero_and_invalid_fallback_is_refused(self):
        with mock.patch.object(window.os,"execv") as execute:
            self.assertEqual(window.main([NS,"/fixture/uu-network-steam","steam://open/games"]),0)
            for invalid in ("uu-network-steam","/fixture/unexpected"):
                self.assertEqual(window.main([NS,invalid]),2)
            execute.assert_not_called()


if __name__=="__main__":
    unittest.main()
