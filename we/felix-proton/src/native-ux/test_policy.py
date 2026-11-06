"""Kernel integration: only disposable Linux user/network namespaces are mutated."""
import contextlib
import json
import os
from pathlib import Path
import select
import subprocess
import tempfile
import unittest
from unittest import mock

from policy import MAX_ENDPOINTS, PROTOCOL, Policy, PolicyError


A="203.0.113.10"
B="203.0.113.11"
C="198.51.100.44"


class IsolatedPolicyTests(unittest.TestCase):
    def setUp(self):
        if os.geteuid()==0: self.skipTest("run as an unprivileged namespace owner")
        self.holder=subprocess.Popen(["unshare","--user","--map-root-user","--net","/bin/sh","-ec",
            "ip link add p0 type dummy; ip addr add 192.0.2.2/24 dev p0; ip link set p0 up; "
            "ip route add default via 192.0.2.1 dev p0; echo ready; exec sleep 45"],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        self.addCleanup(self.close_holder)
        if (not select.select([self.holder.stdout],[],[],4)[0] or self.holder.stdout.readline()!=b"ready\n"):
            self.skipTest("cannot create disposable user+network namespace")
        temp=self.enterContext(tempfile.TemporaryDirectory(prefix="felix-cm-policy-"))
        self.ledger=Path(temp)/"state.json"
        self.fds=[]
        for kind in ("user","net"):
            fd=os.open(f"/proc/{self.holder.pid}/ns/{kind}",os.O_RDONLY)
            self.addCleanup(os.close,fd);self.fds.append(fd)
        self.p=self.enterContext(Policy(*self.fds,self.ledger))
        self.assertNotEqual(self.p.identity[2],os.readlink("/proc/self/ns/net"))

    def close_holder(self):
        self.holder.terminate();self.holder.wait(timeout=3);self.holder.stdout.close()

    def start_uu(self):
        self.p._ip("link","add","UU","type","dummy")
        self.p._ip("-4","addr","add","198.18.0.2/24","dev","UU")
        self.p._ip("link","set","UU","up")
        self.p._ip("-4","route","add",A+"/32","dev","UU","src","198.18.0.2")
        self.p._ip("-4","route","add",B+"/32","dev","UU","src","198.18.0.2")

    def dev(self,addr,proto="tcp",port=443):
        r=self.p._ip("-4","route","get",addr,"ipproto",proto,"dport",port,read=True)[0]
        return r["dev"],r["prefsrc"]

    def test_active_tunnel_and_stop_selectivity(self):
        p=self.p
        self.assertTrue(p.capture_baseline("p0")["changed"])
        self.assertEqual(self.ledger.stat().st_mode & 0o777,0o600)
        self.assertEqual(self.dev(A),("p0","192.0.2.2"))
        p.reconcile([(A,443)])
        self.start_uu()
        self.assertEqual(self.dev(A),("p0","192.0.2.2"))
        self.assertEqual(self.dev(A,"tcp",444),("UU","198.18.0.2"))
        self.assertEqual(self.dev(A,"udp",443),("UU","198.18.0.2"))
        self.assertEqual(self.dev(B),("UU","198.18.0.2"))
        self.assertFalse(p.reconcile([(A,443)])["changed"])
        with self.assertRaisesRegex(PolicyError,"tunnel_active"):p.capture_baseline()
        p._ip("link","del","UU")
        self.assertEqual(self.dev(A),("p0","192.0.2.2"))
        with Policy(*self.fds,self.ledger) as again:
            self.assertFalse(again.reconcile([(A,443)])["changed"])
            self.assertTrue(again.rollback()["changed"])
            self.assertFalse(again.rollback()["changed"])

    def test_slots_add_shrink_and_rollback_preserve_foreign(self):
        p=self.p
        p._ip("-4","route","add","blackhole",C+"/32","table",41200)
        p._ip("-4","rule","add","pref",14300,"to",C+"/32","ipproto","udp","dport",23,"lookup",41200)
        p.capture_baseline()
        state=json.loads(self.ledger.read_bytes())
        self.assertNotEqual(state["pref"],14300);self.assertNotEqual(state["table"],41200)
        r=p.reconcile([(A,443),(A,27017),(B,447)])
        self.assertEqual((r["rules"],r["routes"]),(3,2))
        r=p.reconcile([(A,27017)])
        self.assertEqual((r["rules"],r["routes"]),(1,1))
        p.rollback()
        self.assertTrue(any(str(x.get("table"))=="41200" for x in p._ip("-4","rule","show",read=True)))
        self.assertTrue(p._ip("-4","route","show","table",41200,read=True))

    def test_failed_add_restores_working_set(self):
        p=self.p;p.capture_baseline();p.reconcile([(A,443)])
        real=p._ip_batch
        def fail(commands,**kw):
            commands=list(commands)
            for i,command in enumerate(commands):
                if command[:2]==("rule","add") and B+"/32" in command:
                    # Fail the real batch after adding B's route. Later
                    # deletions in this batch must not run.
                    commands[i]=("invalid-cm-test-command",)
                    try:
                        return real(commands,**kw)
                    except PolicyError:
                        state=json.loads(self.ledger.read_bytes())
                        self.assertEqual(p._inspect(state),({(A,443)},{A,B}))
                        raise
            return real(commands,**kw)
        with mock.patch.object(p,"_ip_batch",side_effect=fail):
            with self.assertRaisesRegex(PolicyError,"netlink_change_failed"):
                p.reconcile([(B,444)])
        self.assertFalse(p.reconcile([(A,443)])["changed"])
        state=json.loads(self.ledger.read_bytes())
        self.assertEqual(state["owned"],[[A,443]])
        self.assertNotIn(B,{r["dst"] for r in p._ip("-4","route","show","table",state["table"],read=True)})

    def test_earlier_rule_override_in_batched_queries_restores_working_set(self):
        p=self.p;p.capture_baseline();p.reconcile([(A,443)])
        p._ip("-4","route","add","table",44000,B+"/32","dev","p0")
        p._ip("-4","rule","add","pref",100,"to",B+"/32","ipproto","tcp","dport",443,"lookup",44000)
        with self.assertRaisesRegex(PolicyError,"earlier_rule_overrides"):
            p.reconcile([(A,443),(C,443),(B,443)])
        state=json.loads(self.ledger.read_bytes())
        self.assertEqual(p._inspect(state),({(A,443)},{A}))
        self.assertTrue(any(r.get("priority")==100 for r in p._ip("-4","rule","show",read=True)))

    def test_foreign_conflict_rejected_and_never_deleted(self):
        p=self.p;p.capture_baseline();p.reconcile([(A,443)])
        state=json.loads(self.ledger.read_bytes())
        p._ip("-4","rule","add","pref",state["pref"],"to",C+"/32","ipproto","tcp","dport",80,"lookup","main")
        with self.assertRaisesRegex(PolicyError,"foreign_rule_conflict"):p.rollback()
        self.assertTrue(self.ledger.exists())
        self.assertTrue(any(r.get("dst")==C for r in p._ip("-4","rule","show",read=True)))
        p._ip("-4","rule","del","pref",state["pref"],"to",C+"/32","ipproto","tcp","dport",80,"lookup","main")
        p.rollback()

    def test_no_host_permission_and_input_errors_preserve_state(self):
        with contextlib.ExitStack() as stack:
            handles=[]
            for kind in ("user","net"):
                fd=os.open("/proc/self/ns/"+kind,os.O_RDONLY);stack.callback(os.close,fd);handles.append(fd)
            with self.assertRaisesRegex(PolicyError,"unsafe_namespace"):
                with Policy(*handles,self.ledger):pass
        p=self.p
        with self.assertRaisesRegex(PolicyError,"baseline_required"):p.reconcile([(A,443)])
        p.capture_baseline();p.reconcile([(A,443)])
        for bad in ([("::1",443)],[(A,0)], [("127.0.0.1",443)],[(B,443)]*(MAX_ENDPOINTS+1)):
            with self.assertRaises(PolicyError):p.reconcile(bad)
        self.assertFalse(p.reconcile([(A,443)])["changed"])

    def test_partial_journal_recovers_and_can_rollback(self):
        p=self.p;p.capture_baseline();p.reconcile([(A,443)])
        state=json.loads(self.ledger.read_bytes())
        state["owned"].append([B,447])
        p._save(state)
        # Simulate abrupt loss after WAL + route but before new rule.
        p._ip("-4","route","add","table",state["table"],B+"/32","via","192.0.2.1","dev","p0",
              "onlink","src","192.0.2.2","proto",PROTOCOL,"metric",42420)
        result=p.reconcile([(C,442)])
        self.assertEqual(result["rules"],1)
        self.assertEqual(p._inspect(json.loads(self.ledger.read_bytes())),({(C,442)},{C}))
        p.rollback()


class BatchTests(unittest.TestCase):
    def test_uncommon_interface_name_uses_individual_commands(self):
        p=Policy(0,0,"unused")
        commands=[("addr","show","dev","p#0"),("route","show","dev","p#0")]
        with mock.patch.object(p,"_ip",return_value=[]) as ip:
            self.assertEqual(p._ip_batch(commands,read=True),[[],[]])
        self.assertEqual(ip.call_args_list,[mock.call("-4",*command,read=True) for command in commands])


if __name__=="__main__":unittest.main()
