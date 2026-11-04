# SPDX-License-Identifier: BSD-3-Clause
import json
from pathlib import Path
import tempfile
import unittest

import signals_beta as s


class Signals(unittest.TestCase):
    def test_private_text_not_emitted(self):
        record = '选择游戏 Alice https://example.org/private?token=Secret 192.0.2.1 error_code=50004'.encode()
        self.assertEqual(s.classify_line(record), {"type": "client_target_selection_mentioned", "code": 50004})
        self.assertEqual(s.classify_line(b"errno=99998"), {"type": "error_code_mentioned"})
        for value in ("123456789", "100.1.2.3", "50004.15"):
            self.assertIsNone(s.classify_line(f"errno={value}".encode()))

    def test_actual_wine_functions_and_client_mentions(self):
        self.assertEqual(s.classify_line(b'123.00:23:47:trace:wintun:WintunStartSession ptr'), {"type": "wintun_start_session_call"})
        self.assertEqual(s.classify_line(b'00:warn:winsock:try_send sendmsg: Permission denied'), {"type": "network_permission_denied"})
        self.assertEqual(s.classify_line('当前系统不支持连接该节点'.encode()), {"type": "client_node_unsupported_mentioned"})
        self.assertEqual(s.classify_line('加速成功'.encode()), {"type": "client_success_mentioned"})
        self.assertEqual(s.classify_line('路由模式'.encode()), {"type": "client_route_mode_mentioned"})
        for record in (b'raw private details', b'\0WintunStartSession', b'x' * s.MAX_LINE + b'WintunStartSession'):
            self.assertIsNone(s.classify_line(record))


class Tail(unittest.TestCase):
    def setUp(self):
        self.prefix = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.logs = self.prefix / s.LOG_DIR
        self.logs.mkdir(parents=True)
        self.uu = self.logs / 'uu.log'

    def test_skip_history_partial_lines_split_append(self):
        history = b'WintunCreateAdapter\npartial old'
        self.uu.write_bytes(history)
        t = s.ClientLogTail(self.prefix)
        with self.uu.open('ab') as f:
            f.write(b' WintunStartSession\nWintunEnd')
        rows = t.poll()
        self.assertFalse(any(x['type'].startswith('wintun_') for x in rows))
        self.assertTrue(any(x['type'] == 'client_log_baseline' and x['offset'] == len(history) for x in rows))
        with self.uu.open('ab') as f:
            f.write(b'Session secret=should-never-appear\n')
        records = t.poll()
        self.assertIn({'type': 'wintun_end_session_call', 'log': 'uu'}, records)
        self.assertNotIn('secret', json.dumps(records))
        self.assertEqual(t.poll(), [])

    def test_rotate_truncate_and_new_source(self):
        self.uu.write_bytes(b'x' * 90 + b'\n')
        t = s.ClientLogTail(self.prefix)
        t.poll()
        self.uu.write_bytes(b'WintunCreateAdapter\n')
        self.assertEqual([r['type'] for r in t.poll()], ['client_log_truncated', 'wintun_create_adapter_call', 'client_log_growth'])
        self.uu.rename(self.logs/'previous')
        self.uu.write_bytes(b'WintunCloseAdapter\n')
        (self.logs/'uu_tun.log').write_bytes(b'')
        records = t.poll()
        self.assertIn('client_log_rotated', [r['type'] for r in records])
        self.assertIn({'type':'client_log_appeared','log':'uu_tun','format':'empty','offset':0,'size':0}, records)

    def test_opaque_hex_and_binary_report_only_sizes(self):
        self.uu.write_bytes(b'0123456789ABCDEF' * 100 + b'\n')
        proxy = self.logs / 'uu_proxy.log'
        proxy.write_bytes(b'\x00\x18WintunStartSession')
        t = s.ClientLogTail(self.prefix)
        initial = t.poll()
        self.assertEqual({r['log']:r.get('format') for r in initial}, {'uu':'opaque_hex', 'uu_tun':None, 'uu_proxy':'opaque_binary'})
        with self.uu.open('ab') as f:
            f.write(b'a' * 2000)
        self.assertEqual(t.poll(), [{'type':'client_log_growth','log':'uu','format':'opaque_hex','from_offset':1601,'to_offset':3601}])

    def test_bounded_budget_and_signals(self):
        self.uu.write_bytes(b'initial header\n')
        t = s.ClientLogTail(self.prefix)
        t.poll()
        with self.uu.open('ab') as f:
            f.write(b'WintunOpenAdapter\n' * 5000)
        rows = t.poll()
        types = [r['type'] for r in rows]
        self.assertIn('client_log_gap', types)
        self.assertIn('client_log_events_limited', types)
        self.assertEqual(types.count('wintun_open_adapter_call'), s.MAX_EVENTS)

    def test_symlink_never_reads_outside_file(self):
        private = self.prefix / 'private'
        private.write_text('WintunOpenAdapter\n')
        self.uu.symlink_to(private)
        t = s.ClientLogTail(self.prefix)
        rows = t.poll()
        self.assertIn({'type':'client_log_unavailable','log':'uu'}, rows)
        self.assertNotIn('wintun_', json.dumps(rows))


if __name__ == '__main__':
    unittest.main()
