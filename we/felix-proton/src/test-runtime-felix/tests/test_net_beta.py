import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import net_beta as net

DEV = b"Inter-| Receive | Transmit\n face |bytes packets errs drop fifo frame compressed multicast|bytes packets errs drop fifo colls carrier compressed\n"
LO = b"lo: " + b"0 " * 16 + b"\n"
UU = b"UU: 19 2 0 0 0 0 0 0 27 3 0 0 0 0 0 0\n"
ROUTE = b"Iface Destination Gateway Flags RefCnt Use Metric Mask MTU Window IRTT\n"
ROW = b" 00000000 00000000 0001 0 0 0 00000000 0 0 0\n"


class NetSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.prefix, self.proc, self.runtime = root / "prefix", root / "proc", root / "xdg"
        key = hashlib.sha256(os.fsencode(self.prefix)).hexdigest()[:16]
        self.session = self.runtime / "shorin-proton-wrapper" / "sessions" / key
        self.session.mkdir(parents=True)
        (self.proc / "self/ns").mkdir(parents=True)
        (self.proc / "self/ns/net").symlink_to("net:[1]")

    def keeper(self):
        p = self.proc / "223"
        (p / "ns").mkdir(parents=True)
        (p / "net").mkdir()
        for name, value in (("keeper.pid", "223"), ("netns", "net:[50]"), ("userns", "user:[49]")):
            (self.session / name).write_text(value)
        for name, value in (("net", "net:[50]"), ("user", "user:[49]")):
            (p / "ns" / name).symlink_to(value)
        (p / "cmdline").write_bytes(b"python3\0-\0" + os.fsencode(self.session) + b"\0")
        (p / "stat").write_text("223 (python3) S" + " 0" * 18 + " 42 0 0\n")
        (p / "comm").write_bytes(b"python3\n")
        (p / "net/dev").write_bytes(DEV + LO)
        (p / "net/route").write_bytes(ROUTE)
        return p

    def sample(self):
        return net._snapshot(self.prefix, self.proc, self.runtime, os.getuid())

    def steam_process(self, pid, ns, executable="steam"):
        p = self.proc / str(pid)
        (p / "ns").mkdir(parents=True)
        (p / "comm").write_bytes(b"steam\n")
        (p / "exe").symlink_to("/fake/" + executable)
        (p / "ns/net").symlink_to(ns)

    def test_absent_leaves_observations_unknown(self):
        self.assertEqual(self.sample(), net._unknown("absent"))
        (self.session / "userns").write_text("user:[50]")
        self.assertEqual(self.sample(), net._unknown())

    def test_wrong_command_namespace_or_owner_fails_closed(self):
        p = self.keeper()
        original = (p / "cmdline").read_bytes()
        for data in (b"sleep\0" + os.fsencode(self.session) + b"\0", original + b"extra\0"):
            (p / "cmdline").write_bytes(data)
            self.assertEqual(self.sample(), net._unknown())
        (p / "cmdline").write_bytes(original)
        self.assertEqual(net._snapshot(self.prefix, self.proc, self.runtime, os.getuid() + 1), net._unknown())
        (self.session / "netns").write_text("net:[1]")
        self.assertEqual(self.sample(), net._unknown())
        (self.session / "netns").write_text("net:[50]")
        (self.session / "userns").write_text("user:[3]")
        self.assertEqual(self.sample(), net._unknown())

    def test_stale_pid_and_marker_symlink_are_unverified(self):
        self.keeper()
        marker = self.session / "keeper.pid"
        marker.write_text("984324")
        self.assertEqual(self.sample(), net._unknown())
        marker.unlink()
        marker.symlink_to("netns")
        self.assertEqual(self.sample(), net._unknown())

    def test_absent_link_and_steam_grouping(self):
        self.keeper()
        self.assertEqual(self.sample(), {"keeper_state": "verified", "uu_device": "absent",
            "uu_ipv4_routes": 0, "uu_rx_bytes": None, "uu_tx_bytes": None, "steam_network": "not_running"})
        self.steam_process(301, "net:[50]", "python3")
        self.assertEqual(self.sample()["steam_network"], "not_running")
        self.steam_process(302, "net:[1]")
        self.assertEqual(self.sample()["steam_network"], "different")
        self.steam_process(303, "net:[50]")
        self.assertEqual(self.sample()["steam_network"], "mixed")
        (self.proc / "302/comm").write_bytes(b"sleep\n")
        self.assertEqual(self.sample()["steam_network"], "same")

    def test_exact_interface_rows_and_privacy(self):
        p = self.keeper()
        (p / "net/dev").write_bytes(DEV + LO + UU)
        (p / "net/route").write_bytes(ROUTE + b"UU" + ROW + b"UU" + ROW + b"UU2" + ROW)
        self.assertEqual(self.sample(), {"keeper_state": "verified", "uu_device": "present",
            "uu_ipv4_routes": 2, "uu_rx_bytes": 19, "uu_tx_bytes": 27, "steam_network": "not_running"})

    def test_incomplete_kernel_read_or_link_change(self):
        p = self.keeper()
        (p / "net/route").write_bytes(ROUTE + b"UU" + ROW)
        r = self.sample()
        self.assertEqual(r["uu_device"], "unknown")
        self.assertIsNone(r["uu_ipv4_routes"])
        (p / "net/dev").write_bytes(DEV + UU)
        (p / "net/route").unlink()
        r = self.sample()
        self.assertEqual(r["uu_device"], "present")
        self.assertIsNone(r["uu_ipv4_routes"])

    def test_reused_pid_during_sample_discards_counts(self):
        p = self.keeper()
        with patch.object(net, "_keeper", side_effect=[(p, 1, "net:[50]"), (p, 2, "net:[50]")]):
            self.assertEqual(self.sample(), net._unknown())


if __name__ == "__main__":
    unittest.main()
