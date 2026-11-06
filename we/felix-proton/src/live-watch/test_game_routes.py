import contextlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

here=Path(__file__).resolve().parent
sys.path.insert(0,str(here.parent/"test-runtime-felix"))
sys.path.insert(0,str(here))
import game_routes as g


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        self.proc=root/"proc"
        self.proc.mkdir()
        self.enterContext(patch.object(g,"PROC",self.proc))
        self.btime=int(time.time())-100
        (self.proc/"stat").write_text(f"btime {self.btime}\n")
        self.logs=root/"logs"
        self.logs.mkdir()
        self.log=self.logs/"gameprocess_log.txt"
        self.log.touch()
        self.game=g.GameRoutes(root/"prefix",self.logs)
        self.enterContext(patch.object(g,"_namespace",lambda p:contextlib.nullcontext(("net:[201]",(330,331)))))
        self.calls=[]
        self.ack=40
        self.recv=8
        self.dev="UU"
        self.extra=b""
        self.enterContext(patch.object(g,"_read_cmd",self.command))

    def command(self,fds,cmd,deadline,limit=0):
        self.calls.append(cmd)
        if cmd[0].endswith("/ss"):
            return f"tcp ESTAB 0 0 192.0.2.7:4000 198.51.100.1:443 ino:900 sk:ab cubic bytes_acked:{self.ack} bytes_received:{self.recv}\n".encode()+self.extra
        if "get" in cmd:
            return [{"dev":self.dev}]
        return [{"dev":"uplink"}]

    def pid(self,appid=570,pid=500,ino=900,comm="dota2",ns="net:[201]"):
        p=self.proc/str(pid)
        (p/"ns").mkdir(parents=True)
        (p/"fd").mkdir()
        (p/"comm").write_text(comm+"\n")
        (p/"exe").symlink_to("/fake/steamapps/common/Dota 2/bin/"+comm)
        (p/"ns/net").symlink_to(ns)
        (p/"stat").write_text(f"{pid} (example) S"+" 0"*18+" 20 0\n")
        (p/"fd/83").symlink_to(f"socket:[{ino}]")
        self.event(appid,pid)
        return p

    def event(self,appid,pid,added=True,when=None):
        when=time.time() if when is None else when
        state="adding PID" if added else "no longer tracking PID"
        with self.log.open("a") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(when))}] AppID {appid} {state} {pid}\n")

    def test_no_game_is_cheap(self):
        with patch.object(g,"_namespace",side_effect=AssertionError):
            self.assertEqual(self.game.poll(),{"games":[]})
        self.assertFalse(self.calls)

    def test_seed_add_delta_idle_and_route_change(self):
        self.pid()
        first=self.game.poll()["games"][0]
        self.assertEqual((first["observed_uu"],first["uu"],first["uu_acked_bytes"]),(1,0,0))
        self.assertIn("first_sample",first["unknown_reasons"])
        self.ack=46;self.recv=21
        row=self.game.poll()["games"][0]
        self.assertEqual((row["uu"],row["uu_acked_bytes"],row["uu_received_bytes"]),(1,6,13))
        self.assertNotIn("198.51",json.dumps(row))
        idle=self.game.poll()["games"][0]
        self.assertEqual((idle["observed_uu"],idle["uu"]),(1,0))
        self.dev="uplink";self.recv+=10
        moved=self.game.poll()["games"][0]
        self.assertEqual((moved["observed_direct"],moved["direct_received_bytes"]),(1,0))
        self.assertIn("route_or_counter_changed",moved["unknown_reasons"])
        self.recv+=19
        self.assertEqual(self.game.poll()["games"][0]["direct_received_bytes"],19)
        self.event(570,500,False)
        before=len(self.calls)
        self.assertEqual(self.game.poll(),{"games":[]})
        self.assertEqual(len(self.calls),before)

    def test_unconfirmed_or_protection_images_do_not_open_fds(self):
        self.pid(comm="EasyAntiCheat")
        with patch.object(g,"_fd_inodes",side_effect=AssertionError):
            row=self.game.poll()["games"][0]
        self.assertIn("main_image_unconfirmed",row["unknown_reasons"])
        self.assertFalse(self.calls)

    def test_ue_renamed_leader_requires_first_executable_token(self):
        p=self.pid(appid=1808500,comm="GameThread")
        (p/"exe").unlink();(p/"exe").symlink_to("/runtime/wine64-preloader")
        cmd=p/"cmdline"
        for raw in (b"Z:\\steamapps\\common\\ARC\\PioneerGame.exe\0/unused-private-value\0",
                    b"/runtime/wine64-preloader\0C:\\games\\PioneerGame.exe\0secret\0"):
            cmd.write_bytes(raw)
            self.assertTrue(g._main_image(1808500,p))
        for raw in (b"shell\0-c\0PioneerGame.exe\0", b"launcher.exe\0PioneerGame.exe\0",
                    b"safe.exe\0cmdline mentions PioneerGame.exe\0",b"a"*1025+b"PioneerGame.exe\0"):
            cmd.write_bytes(raw)
            self.assertFalse(g._main_image(1808500,p))
        (p/"comm").write_text("protected\n")
        cmd.unlink()
        self.assertFalse(g._main_image(1808500,p))

    def test_other_namespace_and_reused_pid(self):
        p=self.pid(ns="net:[7]")
        row=self.game.poll()["games"][0]
        self.assertIn("different_namespace",row["unknown_reasons"])
        self.assertFalse(self.calls)
        (p/"stat").write_text("500 (other) S"+" 0"*18+" 25 0\n")
        self.game.poll()
        self.assertFalse(self.game.tracked)
        self.assertFalse(self.calls)

    def test_socket_families_and_unattributable_udp(self):
        self.pid()
        (self.proc/"500/fd/89").symlink_to("socket:[922]")
        self.extra=b"udp UNCONN 0 0 *:8834 *:* ino:922 sk:cd\n"+b"tcp ESTAB 0 0 [::ffff:192.0.2.7]:20 [::ffff:198.51.100.7]:443 ino:777 sk:8 bytes_acked:5\n"
        row=self.game.poll()["games"][0]
        self.assertEqual(row["observed_uu"],1)
        self.assertIn("udp_no_peer",row["unknown_reasons"])
        self.assertTrue(all("198.51.100.7" not in cmd for cmd in self.calls))

    def test_settle_after_read_error(self):
        self.pid()
        self.game.poll()
        with patch.object(g,"_read_cmd",side_effect=TimeoutError):
            self.assertIn("sample_unavailable",self.game.poll()["games"][0]["unknown_reasons"])
        self.ack+=30
        self.assertEqual(self.game.poll()["games"][0]["uu_acked_bytes"],0)

    def test_stale_event_does_not_adopt_new_pid(self):
        self.pid()
        self.log.write_text("")
        self.event(570,500,when=self.btime-90)
        self.assertEqual(self.game.poll(),{"games":[]})
        self.assertFalse(self.calls)

if __name__=="__main__":unittest.main()
