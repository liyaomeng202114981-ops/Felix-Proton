# SPDX-License-Identifier: BSD-3-Clause
import json
from pathlib import Path
import tempfile
import unittest
import steam_events as s

STAMP = b'[2026-11-04 23:11:59] '
TAG = b'[Logged Off, 0, 0] [U:1:123456789] '
OK = TAG+b"RecvMsgClientLogOnResponse() : [U:1:123456789] 'OK'"
CONNECT = TAG+b'Connect() starting connection (secret.example.org:501, WebSocket)'
OFF = TAG+b"ConnectionDisconnected('Remote timeout') : 'Failure' (192.0.2.1:443)"
RATE = b'Current download rate: 30.125 Mbps'


def row(text): return STAMP+text+b'\n'


class SteamFormat(unittest.TestCase):
    def classify(self, source, msg):
        return s.classify(source, STAMP+msg)

    def test_cm_actual_phrases_and_non_event_negation(self):
        for msg,kind in [(OK,'cm_logon_ok'),(CONNECT,'cm_connecting'),(OFF,'cm_disconnected'),
                         (TAG+b"ConnectFailed() : 'Connection Timeout'",'cm_connect_failed')]:
            e=self.classify('connection',msg)
            self.assertEqual(e['type'],kind)
            self.assertNotIn('123456789',json.dumps(e))
        self.assertEqual(self.classify('connection', TAG+b'StartAutoReconnect() will retry in 12.5 seconds (attempt 4)')['retry_seconds'],12.5)
        self.assertIsNone(self.classify('connection', TAG+b'ConnectionDisconnected() not auto reconnecting due to disabled policy'))

    def test_content_and_typed_redaction(self):
        for msg,kind,err in [(b'Failed to get new SteamPipe download sources','download_source_failed','source_unavailable'),
                             (b'SomeClass::Query failed (Transport Response Not Sent / Result No Connection)','content_no_connection','no_connection'),
                             (b'AppID 42 update job canceled : Failed downloading 10236 chunks (No connection)','download_update_error','no_connection'),
                             (b'AppID 42 scheduler finished : removed from schedule (result Disk write failure, state 0x0)','download_scheduler_finished','disk_write')]:
            e=self.classify('content',msg+b' secret://user@192.0.2.1/?token=secret')
            self.assertEqual((e['type'],e['error']),(kind,err))
            self.assertNotIn('secret',json.dumps(e))
            if msg.startswith(b'AppID'): self.assertEqual(e['appid'],42)
        self.assertEqual(self.classify('content',b'AppID 42 scheduler finished : removed (result No Error, state 0x0)')['exitcode'],'ok')
        self.assertEqual(self.classify('content',b'AppID 42 update started : download 1/2')['type'],'download_started')

    def test_rate_does_not_attribute_global_measurement(self):
        self.assertEqual(self.classify('content',RATE)['rate_mbps'],30.125)
        self.assertNotIn('appid',self.classify('content',RATE))
        self.assertEqual(self.classify('content',b'AppID 42 Current download rate: 5 MB/s')['rate_mbps'],40)
        self.assertEqual(self.classify('content',b'AppID 42 Current download rate: 5 MB/s')['appid'],42)
        self.assertIsNone(self.classify('content',b'AppID 4294967296 Current download rate: 1 Mbps'))


class Following(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.cm=self.root/'connection_log.txt'; self.content=self.root/'content_log.txt'
        self.cm.write_bytes(row(OK))
        self.content.write_bytes(row(RATE)+STAMP+b'old unfinished')
        self.reader=s.SteamEvents(self.root)

    def add(self,path,data):
        with path.open('ab') as f: f.write(data)

    def test_baseline_latest_snapshot_and_partial_append(self):
        self.assertEqual(self.reader.snapshot()['state'],'logged_on')
        first=self.reader.poll()
        self.assertEqual([e['type'] for e in first], ['steam_log_baseline']*2)
        self.assertEqual(self.reader.poll(),[])
        self.add(self.content,b' Current download rate: 3 Mbps\n'+STAMP+b'Current download rate:')
        self.assertEqual(self.reader.poll(),[])
        self.add(self.cm,row(OFF))
        self.add(self.content,b' 25.5 Mbps\n')
        events=self.reader.poll()
        self.assertEqual([e['type'] for e in events],['cm_disconnected','download_rate'])
        self.assertEqual(self.reader.snapshot()['state'],'disconnected')
        self.assertEqual(self.reader.poll(),[])

    def test_rotate_and_shrink_noted_and_new_file_read(self):
        self.reader.poll()
        self.cm.rename(self.root/'old')
        self.cm.write_bytes(row(CONNECT))
        events=self.reader.poll()
        self.assertEqual([e['type'] for e in events],['steam_log_rotated','steam_log_gap','cm_connecting'])
        self.cm.write_bytes(b'')
        self.assertEqual(self.reader.poll()[0]['type'],'steam_log_truncated')
        self.assertEqual(self.reader.snapshot()['state'],'unknown')

    def test_copytruncate_regrow_and_missing(self):
        self.reader.poll()
        self.cm.write_bytes(row(CONNECT)+b'\n'*120)
        self.assertEqual(self.reader.poll()[0]['type'],'steam_log_rewritten')
        self.cm.unlink()
        self.assertEqual(self.reader.poll()[0]['type'],'steam_log_missing')
        self.assertEqual(self.reader.poll(),[])
        self.cm.write_bytes(row(OK))
        self.assertEqual(self.reader.poll()[-1]['type'],'cm_logon_ok')

    def test_backlog_cap_long_lines_and_event_budget(self):
        self.reader.poll()
        self.add(self.content,b'\n'+(row(RATE)*4000)+b'x'*10000+b'\n')
        rows=self.reader.poll()
        self.assertTrue(any(r.get('reason')=='byte_limit' for r in rows))
        self.assertTrue(any(r.get('reason')=='long_line' for r in rows))
        self.assertTrue(any(r.get('reason')=='event_limit' for r in rows))
        self.assertEqual(sum(r['type']=='download_rate' for r in rows), s._LIMIT)

    def test_no_symlink_follow(self):
        self.cm.unlink(); self.cm.symlink_to(self.content)
        rows=self.reader.poll()
        self.assertIn('steam_log_unavailable',[r['type'] for r in rows])


if __name__=='__main__':
    unittest.main()
