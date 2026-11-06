# SPDX-License-Identifier: BSD-3-Clause
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

import endpoints as e

A = 'cmp1-sgp1.steamserver.net'
B = 'cmp2-tyo3.steamserver.net'
IP = '45.121.184.21'
V6 = '2606:4700:4700::1111'
WALL = 1793700000.0


def msg(body, t=WALL):
    stamp=time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(t))
    return f'[{stamp}] [Connecting, 0, 0] [U:1:123456789] {body}'.encode()


def official(rows):
    return json.dumps({'response':{'success':True,'serverlist':rows}}).encode()


def ws(endpoint):
    return {'endpoint':endpoint,'legacy_endpoint':'8.8.8.8:53','type':'websockets','realm':'steamglobal'}


class Parser(unittest.TestCase):
    def test_public_api_host_port_and_no_legacy_or_other_transports(self):
        payload=official([ws(A+':443'),ws(A+':27018'),ws(A+':443'),ws(f'[{V6}]:443'),
                          ws('127.0.0.1:443'),ws('10.0.0.1:80'),ws('198.18.0.1:443'),
                          ws('224.1.2.3:443'),ws('host.steamserver.net.example:443'),
                          ws('https://'+B+'/auth?a=token'),dict(ws(IP+':27017'),type='netfilter'),
                          dict(ws(IP+':443'),realm='somethingelse')])
        self.assertEqual(e.directory_rows(payload),[(A,443),(A,27018)])
        self.assertIn((V6,443),e.directory_rows(payload,(6,)))
        for invalid in (b'{}',b'[]',b'{"response":{"success":false}}',official([]),b'x'*150000):
            with self.assertRaises(ValueError): e.directory_rows(invalid)

    def test_real_grammar_only_and_first_remote_not_local(self):
        self.assertEqual(e.parse_cm_line(msg(f'PingWebSocketCM() ({A}:27019) starting...'))[:2],('candidate',(A,27019)))
        self.assertEqual(e.parse_cm_line(msg(f'Connect() starting connection (eNetQOSLevelHigh, {A}:443, WebSocket)'))[:2],('candidate',(A,443)))
        self.assertEqual(e.parse_cm_line(msg(f'ConnectionCompleted() ({IP}:27017, TCP) local address (192.168.0.3:34222)'))[:2],('completed',(IP,27017)))
        for text in (f'notice token=PingWebSocketCM() ({A}:443) starting...',f'ConnectionDisconnected() ({IP}:27017, TCP)',
                     'PingWebSocketCM() (evil.example:443) starting...','PingWebSocketCM() (8.8.8.8:443) starting...',
                     'ConnectionCompleted() (127.0.0.1:443, TCP) local address (8.8.8.8:27017)',
                     f'ConnectionCompleted() ({IP}:27017, UDP)',f'PingWebSocketCM() ({A}:0) starting...'):
            self.assertIsNone(e.parse_cm_line(msg(text)),text)

    def test_link_local_multicast_ambiguous_ipv6_and_ports(self):
        for text in ('2606:4700::1:443','[fe80::1234%enp5s0]:443','[ff02::1]:443','[::1]:443','0.0.0.0:27020',
                     '127.0.0.1:1','8.8.8.8:+53','cmp1-sgp1.steamserver.net:443/','foo.steamserver.net.evil:27018'):
            self.assertIsNone(e._pair(text,(4,6)),text)


class DirectoryProxy(unittest.TestCase):
    def test_explicit_proxy_and_bypass_keep_standard_urllib_behavior(self):
        for env in ({'https_proxy': 'http://127.0.0.1:1234'}, {'no_proxy': e.DIRECTORY_HOST}):
            with self.subTest(env=env), mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(e, '_desktop_proxy') as desktop, \
                    mock.patch.object(e, '_read_directory') as read:
                e._fetch((4,))
                desktop.assert_not_called()
                read.assert_called_once_with((4,), e.urllib.request.getproxies())

    def test_desktop_proxy_is_scoped_and_transport_failure_retries_direct(self):
        proxy = 'http://127.0.0.1:1234'
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(e, '_desktop_proxy', return_value=proxy), \
                mock.patch.object(e, '_read_directory', side_effect=[ConnectionRefusedError, [(A, 443)]]) as read:
            self.assertEqual(e._fetch((4,)), [(A, 443)])
            self.assertEqual(read.call_args_list, [mock.call((4,), {'https': proxy}), mock.call((4,), {})])


class WorkerWake(unittest.TestCase):
    def test_directory_and_dns_results_wake_poll(self):
        with tempfile.TemporaryDirectory() as root:
            cm = e.CMEndpoints(Path(root)/'connection_log.txt')
            self.addCleanup(cm.close)
            with mock.patch.object(e, '_fetch', return_value=[(B,443)]), \
                    mock.patch.object(e, '_resolve', return_value=[IP]):
                self.assertEqual(cm.poll(), set())
                self.assertTrue(cm.wait_for_results(2))
                self.assertEqual(cm.poll(), set())
                self.assertTrue(cm.wait_for_results(2))
                self.assertEqual(cm.poll(), {(IP,443)})
                self.assertFalse(cm.wait_for_results(0))


class Lookup(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.log=self.root/'connection_log.txt'
        self.log.touch()
        self.now=10_000.
        self.wall=WALL
        self.enterContext(mock.patch.object(e.time,'monotonic',side_effect=lambda:self.now))
        self.enterContext(mock.patch.object(e.time,'time',side_effect=lambda:self.wall))
        self.cm=e.CMEndpoints(self.log)
        self.addCleanup(self.cm.close)
        self.direct=[(B,443)]
        self.hosts={B:[IP],A:['8.8.8.8']}
        self.attempts=[]
        # Deterministic queued worker completions, retaining poll's normal one-way lifecycle.
        def worker(key,func,*args):
            self.cm.pending.add(key)
            self.attempts.append(key)
            self.cm.results.put((key,self.direct if key[0]=='directory' else self.hosts.get(key[1])))
        self.enterContext(mock.patch.object(self.cm,'_worker',side_effect=worker))

    def tick(self,seconds=1,live=()):
        self.now+=seconds
        self.wall+=seconds
        return self.cm.poll(live)

    def append(self,text,age=0):
        with self.log.open('ab') as f: f.write(msg(text,self.wall-age)+b'\n')

    def test_prefetch_exact_endpoints_before_any_socket(self):
        self.append(f'PingWebSocketCM() ({A}:27019) starting...')
        self.cm.poll();self.tick()
        self.assertEqual(self.tick(),{('8.8.8.8',27019),(IP,443)})
        self.assertTrue(self.cm.status()['ready'])
        self.assertFalse(any(v in str(self.cm.status()) for v in (A,IP,'123456789')))

    def test_socket_alone_and_unconfirmed_numeric_log_not_authority(self):
        unknown=('9.9.9.9',443)
        port=(IP,27017)
        self.direct=[]
        self.append(f'ConnectionCompleted() ({IP}:27017, TCP) local address (9.9.9.9:443)')
        self.assertEqual(self.tick(live=[unknown]),set())
        self.assertEqual(self.tick(live=[port,unknown]),{port})
        self.assertNotIn(unknown,self.tick(live=[unknown]))
        self.tick(e.COMPLETED_TTL+e.LIVE_TTL+1)
        self.assertEqual(self.tick(live=[port]),set())

    def test_old_log_is_not_renewed_at_start(self):
        self.direct=[]
        self.append(f'PingWebSocketCM() ({A}:443) starting...',age=e.HINT_TTL+2)
        self.append(f'ConnectionCompleted() ({IP}:443, TCP)',age=e.COMPLETED_TTL+2)
        self.cm.poll([(IP,443)]);self.tick()
        self.assertEqual(self.tick(live=[(IP,443)]),set())
        self.assertFalse(any(k[0]=='dns' for k in self.attempts))

    def test_directory_or_dns_failure_retains_existing_positive_until_expiry(self):
        self.cm.poll();self.tick();self.tick()
        self.direct=None; self.hosts={}
        self.assertIn((IP,443),self.tick(91))
        self.assertIn((IP,443),self.tick())
        self.assertNotIn((IP,443),self.tick(e.DNS_TTL+1))
        self.tick(e.DIRECTORY_TTL)
        self.assertNotIn((IP,443),self.tick())

    def test_duplicate_hosts_multiple_ports_no_network_widening_and_cap(self):
        self.cm.limit=2
        self.direct=[(A,27017),(A,27018),(A,27019)]
        self.cm.poll();self.tick();self.tick()
        self.assertEqual(self.attempts.count(('dns',A)),1)
        got=self.tick(live=[('8.8.8.8',27019),('8.8.8.8',443),('8.8.8.8',27016)])
        self.assertEqual(len(got),2)
        self.assertIn(('8.8.8.8',27019),got)
        self.assertNotIn(('8.8.8.8',443),got)
        self.assertNotIn(('8.8.8.8',27016),got)

    def test_rotate_partial_and_malicious_symlink(self):
        self.direct=[]
        with self.log.open('ab') as f: f.write(msg(f'PingWebSocketCM() ({A}:443) starting...')[:-3])
        self.cm.poll()
        self.log.rename(self.root/'old')
        self.log.write_bytes(msg(f'PingWebSocketCM() ({B}:27020) starting...')+b'\n')
        self.tick();self.tick()
        self.assertIn((IP,27020),self.tick())
        self.log.unlink();self.log.symlink_to(self.root/'old')
        self.assertFalse(any(h==A for h,_ in self.cm.hints))

    def test_close_never_schedules_another_request(self):
        self.cm.close()
        self.assertEqual(self.tick(),set())
        self.assertFalse(self.attempts)
        self.assertFalse(self.cm.status()['ready'])


if __name__ == '__main__':
    unittest.main()
