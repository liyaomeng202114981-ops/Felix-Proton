# SPDX-License-Identifier: BSD-3-Clause
import ipaddress
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from cm_guard import _live


NAMESPACE = 'net:[1234]'
HEADER = 'sl local_address remote_address st tx_queue rx_queue tr tm->when retrnsmt uid timeout inode\n'


def record(local, peer, port, inode, state='01'):
    def endpoint(ip, port):
        packed = ipaddress.ip_address(ip).packed
        words = ''.join(f'{word:08X}' for word, in struct.iter_unpack('=I', packed))
        return f'{words}:{port:04X}'
    return f'0: {endpoint(local, 45000)} {endpoint(peer, port)} {state} 0:0 0:0 0 1000 0 {inode}\n'


class LiveSteamSockets(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.proc = Path(self.tmp.name)
        self.p = self.proc/'271'
        (self.p/'fd').mkdir(parents=True)
        (self.p/'net').mkdir()
        (self.p/'ns').mkdir()
        (self.p/'ns/net').symlink_to(NAMESPACE)
        (self.p/'comm').write_bytes(b'steam\n')
        (self.p/'exe').symlink_to('/test/steam')
        (self.p/'fd/7').symlink_to('socket:[123]')
        for table in ('tcp', 'tcp6'):
            (self.p/'net'/table).write_text(HEADER)

    def scan(self):
        return _live(None, NAMESPACE, proc=self.proc)

    def test_returns_ipv4_and_normalized_dual_stack_sockets(self):
        (self.p/'fd/8').symlink_to('socket:[124]')
        (self.p/'net/tcp').write_text(HEADER + record('192.168.42.5', '1.1.1.1', 443, 123))
        (self.p/'net/tcp6').write_text(HEADER + record('::ffff:172.19.0.2', '::ffff:8.8.8.8', 27017, 124, '02'))
        self.assertCountEqual(self.scan(), [('192.168.42.5', ('1.1.1.1', 443)),
                                           ('172.19.0.2', ('8.8.8.8', 27017))])

    def test_unspecified_source_does_not_hide_mapped_peer(self):
        (self.p/'net/tcp6').write_text(HEADER + record('::', '::ffff:8.8.8.8', 443, 123, '02'))
        self.assertEqual(self.scan(), [('::', ('8.8.8.8', 443))])

    def test_native_ipv6_foreign_inodes_and_inactive_sockets_are_excluded(self):
        (self.p/'net/tcp6').write_text(HEADER + record('2001:db8::1', '2606:4700:4700::1111', 443, 123))
        (self.p/'net/tcp').write_text(HEADER + record('192.168.0.1', '8.8.8.8', 443, 555)
                                      + record('192.168.0.1', '1.1.1.1', 443, 123, '06'))
        self.assertEqual(self.scan(), [])

    def test_fd_directory_denied_refuses_hot_takeover(self):
        original = Path.iterdir
        def restricted(path):
            if path == self.p/'fd':
                raise PermissionError()
            return original(path)
        with patch.object(Path, 'iterdir', restricted), self.assertRaisesRegex(RuntimeError, '^cm_steam_sockets_unreadable$'):
            self.scan()

    def test_fd_link_denied_refuses_but_closed_descriptor_is_ignored(self):
        original = os.readlink
        def scan_with(error):
            def restricted(path):
                if path == self.p/'fd/7':
                    raise error
                return original(path)
            with patch.object(os, 'readlink', restricted):
                return self.scan()
        with self.assertRaisesRegex(RuntimeError, '^cm_steam_sockets_unreadable$'):
            scan_with(PermissionError())
        self.assertEqual(scan_with(FileNotFoundError()), [])

    def test_tcp_table_denied_never_returns_partial_live_result(self):
        (self.p/'net/tcp').write_text(HEADER + record('192.168.0.1', '1.1.1.1', 443, 123))
        original = Path.read_text
        for table in ('tcp', 'tcp6'):
            def restricted(path):
                if path == self.p/'net'/table:
                    raise PermissionError()
                return original(path)
            with self.subTest(table=table), patch.object(Path, 'read_text', restricted):
                with self.assertRaisesRegex(RuntimeError, '^cm_steam_sockets_unreadable$'):
                    self.scan()

    def test_known_steam_with_truncated_table_is_unknown(self):
        (self.p/'net/tcp6').write_text('')
        with self.assertRaisesRegex(RuntimeError, '^cm_steam_sockets_unreadable$'):
            self.scan()

    def test_other_namespace_is_not_inspected(self):
        (self.p/'ns/net').unlink()
        (self.p/'ns/net').symlink_to('net:[5555]')
        (self.p/'net/tcp').unlink()
        self.assertEqual(self.scan(), [])


if __name__ == '__main__':
    unittest.main()
