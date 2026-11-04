# SPDX-License-Identifier: BSD-3-Clause
"""Temporary home, GNU-style tar fixtures and a real zstd process. No client runs."""
import hashlib
import io
import os
from pathlib import Path
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bootstrap as b


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.d = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.root = self.d/'.steam/debian-installation'
        (self.root/'steamapps').mkdir(parents=True)
        (self.root/'steam.sh').touch()
        self.wrapper = self.tool('wrapper', '--netns --runner --prefix')
        self.pasta = self.tool('pasta', '--config-net --ns-mac-addr --no-pidns')
        self.steam = self.d/'steam'
        self.steam.symlink_to(self.tool('bin_steam.sh', ''))
        self.args = dict(home=self.d, wrapper=self.wrapper, pasta=self.pasta, steam=self.steam)
        self.enterContext(mock.patch.dict(os.environ, {'XDG_DATA_HOME':str(self.d/'data')}))

    def tool(self, name, help_text):
        p = self.d/name
        p.write_text(f"#!/bin/sh\nif [ \"$1\" = --help ]; then echo '{help_text}'; else exit 99; fi\n")
        p.chmod(0o755)
        return p

    def make_archive(self, extra=()):
        f = io.BytesIO()
        with tarfile.open(fileobj=f, mode='w') as tar:
            members = [('', 'dir', ''), ('felix','dir','')]
            members += [(n,'file','installer fixture') for n in b.REQUIRED]
            members += [('linked-runner','link','proton')] + list(extra)
            for name, kind, text in members:
                info = tarfile.TarInfo(b.TOOL+'/'+name if name else b.TOOL)
                info.mode = 0o755
                if kind == 'dir':
                    info.type = tarfile.DIRTYPE
                elif kind == 'link':
                    info.type, info.linkname = tarfile.SYMTYPE, text
                elif kind == 'hardlink':
                    info.type, info.linkname = tarfile.LNKTYPE, text
                else:
                    info.size = len(text.encode())
                tar.addfile(info, io.BytesIO(text.encode()) if kind == 'file' else None)
        data = subprocess.check_output(['zstd','-qc'], input=f.getvalue())
        path=self.d/'fixture.tar.zst'
        path.write_bytes(data)
        self.enterContext(mock.patch.object(b, 'SHA256', hashlib.sha256(data).hexdigest()))
        return path

    def test_debian_root_and_public_steam_alias_without_installing(self):
        r = b.discover(**self.args)
        self.assertTrue(r['ready'], r['issues'])
        self.assertEqual(r['steam_root'], str(self.root))
        self.assertEqual(r['steam_real'], str(self.steam))
        self.assertEqual(r['pasta_bin_dir'], str(self.pasta.parent))
        self.assertFalse((self.root/'compatibilitytools.d').exists())

    def test_active_steam_root_precedes_unrelated_library(self):
        actual = self.d/'another Steam'
        (actual/'steamapps').mkdir(parents=True)
        (actual/'steam.sh').touch()
        (self.d/'.steam/root').symlink_to(actual)
        self.assertEqual(b.discover(**self.args)['steam_root'], str(actual))
        self.assertFalse(b.discover(**self.args, steam_root=actual/'steamapps')['ready'])

    def test_old_pasta_explicitly_rejected(self):
        self.tool('pasta','--config-net --ns-mac-addr')
        r=b.discover(**self.args)
        self.assertFalse(r['ready'])
        self.assertTrue(any('--no-pidns' in issue for issue in r['issues']))

    def test_local_pe_validation_and_dll_rejected(self):
        data = bytearray(512)
        data[:2] = b'MZ'
        struct.pack_into('<I',data,60,64)
        data[64:68] = b'PE\0\0'
        struct.pack_into('<HH',data,68,0x14c,1)
        struct.pack_into('<HHH',data,84,224,2,0x10b)
        exe=self.d/'official installer.EXE'
        exe.write_bytes(data)
        path,digest = b.inspect_installer(exe)
        self.assertEqual((path,digest), (str(exe),hashlib.sha256(data).hexdigest()))
        struct.pack_into('<H',data,86,0x2002)
        exe.write_bytes(data)
        with self.assertRaises(b.SetupError): b.inspect_installer(exe)
        exe.write_bytes(b'MZtruncated')
        with self.assertRaises(b.SetupError): b.inspect_installer(exe)

    def test_atomic_install_existing_reuse_and_changed_file_refusal(self):
        arc = self.make_archive()
        r = b.prepare(arc, **self.args)
        self.assertEqual(r['install_status'],'installed')
        self.assertEqual(b.prepare(arc, **self.args)['install_status'],'existing')
        dest=Path(r['runner_dir'])
        self.assertTrue((dest/'linked-runner').is_symlink())
        (dest/'proton').write_text('unknown local content')
        with self.assertRaises(b.SetupError): b.prepare(arc, **self.args)
        self.assertEqual((dest/'proton').read_text(),'unknown local content')

    def test_unknown_extra_is_preserved(self):
        arc=self.make_archive()
        out=Path(b.prepare(arc,**self.args)['runner_dir'])
        extra=out/'private-note'
        extra.write_text('keep')
        with self.assertRaises(b.SetupError): b.prepare(arc,**self.args)
        self.assertEqual(extra.read_text(),'keep')

    def test_wrong_hash_refused_before_creating_any_directory(self):
        arc=self.make_archive()
        arc.write_bytes(b'not the release')
        with self.assertRaisesRegex(b.SetupError,'SHA-256'): b.install_runner(arc,self.root)
        self.assertFalse((self.root/'compatibilitytools.d').exists())

    def test_unsafe_archive_refused_without_a_partial_target(self):
        cases = [('jump','link','../../outside'), ('../stray','file','bad'), ('proton','file','dup'),
                 ('linked-runner/nested','file','bad'), ('bad','hardlink','outside')]
        for extra in cases:
            with self.subTest(name=extra[0]):
                arc=self.make_archive([extra])
                with self.assertRaises(b.SetupError): b.install_runner(arc,self.root)
                self.assertEqual(list((self.root/'compatibilitytools.d').iterdir()),[])

    def test_existing_symlink_dir_is_never_replaced(self):
        arc=self.make_archive()
        compat=self.root/'compatibilitytools.d'
        compat.mkdir()
        outside=self.d/'outside'
        outside.mkdir()
        (compat/b.TOOL).symlink_to(outside)
        with self.assertRaises(b.SetupError): b.install_runner(arc,self.root)
        self.assertEqual(list(outside.iterdir()), [])
        self.assertTrue((compat/b.TOOL).is_symlink())


if __name__=='__main__':
    unittest.main()
