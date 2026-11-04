#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Update the local native-icon preview. test.1 stays byte-identical; CM changes are launcher Python."""
import ast
import fcntl
import hashlib
import os
from pathlib import Path
import re
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT/'src/native-ux'
OUT = ROOT/'releases'
NAME = 'Felix-UU-原图标模式-本地预览.zip'
RUNTIME = 'felix-proton-uu-test-0.1.0-test.1.tar.zst'
RUNTIME_SHA = '320d1a9fce1bd4a885c6cc88c35db50411234c0e5f477e167e15460d09362fea'
TOP = 'Felix-UU/'


def hash_stream(f):
    h = hashlib.sha256()
    for block in iter(lambda: f.read(1024*1024), b''):
        h.update(block)
    return h.hexdigest()


def inputs():
    entry = SRC/'enable.py'
    assignments = [node for node in ast.parse(entry.read_text(encoding='utf-8')).body
                   if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id=='SOURCES'
                                                          for t in node.targets)]
    if len(assignments) != 1:
        raise ValueError('expected one SOURCES declaration in enable.py')
    sources = ast.literal_eval(assignments[0].value)
    if (not isinstance(sources, (tuple,list)) or 'enable.py' not in sources or
            not all(isinstance(x,str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*\.py',x) for x in sources)):
        raise ValueError('invalid SOURCES; only top-level Python launcher sources are accepted')
    tests = sorted(p.name for p in SRC.glob('test_*.py'))
    if not tests or not all(re.fullmatch(r'test_[A-Za-z0-9_]+\.py',x) for x in tests):
        raise ValueError('invalid test file names')
    names = ['README.md','LICENSE','LICENSE.proton',*sources,*tests]
    if len(names) != len(set(names)):
        raise ValueError('duplicate input names')
    paths = [SRC/name for name in names]
    paths.append(OUT/'felix-proton-uu-0.1.0-test.1'/RUNTIME)
    if any(p.is_symlink() or not p.is_file() for p in paths):
        raise ValueError('required input missing or not an ordinary file')
    return paths


def sync(path):
    with path.open('rb') as f:
        os.fsync(f.fileno())


def main():
    paths = inputs()
    with paths[-1].open('rb') as base:
        if hash_stream(base) != RUNTIME_SHA:
            raise ValueError('the frozen test.1 runner checksum does not match')
    target = OUT/NAME
    checksum = OUT/(NAME+'.sha256')
    dfd=os.open(OUT,os.O_RDONLY|os.O_DIRECTORY)
    try:
        fcntl.flock(dfd,fcntl.LOCK_EX)
        for path in (target,checksum):
            if path.is_symlink() or (path.exists() and not path.is_file()):
                raise ValueError('refusing to replace a non-regular destination')
        # Same filesystem as outputs. Only fully checked files reach the public names.
        with tempfile.TemporaryDirectory(prefix='.native-preview-',dir=OUT) as tmp:
            stage = Path(tmp)
            archive, digestfile = stage/NAME, stage/(NAME+'.sha256')
            with ZipFile(archive,'x',compression=ZIP_DEFLATED,compresslevel=9,allowZip64=True) as z:
                for p in paths:
                    z.write(p,TOP+p.name,compress_type=ZIP_STORED if p.name==RUNTIME else ZIP_DEFLATED)
            with ZipFile(archive) as z:
                if z.namelist() != [TOP+p.name for p in paths] or z.testzip() is not None:
                    raise ValueError('ZIP member list or CRC validation failed')
                if any(z.getinfo(TOP+p.name).compress_type !=
                       (ZIP_STORED if p.name==RUNTIME else ZIP_DEFLATED) for p in paths):
                    raise ValueError('unexpected ZIP compression method')
                with z.open(TOP+RUNTIME) as runtime:
                    if hash_stream(runtime) != RUNTIME_SHA:
                        raise ValueError('embedded runner checksum does not match')
            with archive.open('rb') as f:
                digest=hash_stream(f)
            digestfile.write_text(f'{digest}  {NAME}\n',encoding='utf-8')
            for path in (archive,digestfile):
                path.chmod(0o644)
                sync(path)
            # POSIX rename is atomic for each path. Retain the old pair privately
            # so that an ordinary error during the second rename can be rolled back.
            old = stage/'previous.zip'
            if target.exists():
                os.link(target,old)
            os.replace(archive,target)
            try:
                os.replace(digestfile,checksum)
            except BaseException:
                if old.exists():
                    os.replace(old,target)
                else:
                    target.unlink()
                os.fsync(dfd)
                raise
            os.fsync(dfd)
    finally:
        os.close(dfd)
    print(f'{target}\nSHA-256 {digest}\n{len(paths)} files; verified frozen test.1 SHA-256 {RUNTIME_SHA}')
    print('原 test.1 运行器未重编。新增的 Steam CM 保护随启动层 Python 源码交付。')


if __name__=='__main__':
    main()
