#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""User-space, version-locked installer for the local Felix UU test runner."""
from __future__ import annotations

import argparse
import contextlib
import ctypes
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import posixpath
import re
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile


TOOL = 'felix-proton-uu-test-0.1.0-test.1'
ARCHIVE = TOOL + '.tar.zst'
SHA256 = '320d1a9fce1bd4a885c6cc88c35db50411234c0e5f477e167e15460d09362fea'
REQUIRED = ('proton', 'compatibilitytool.vdf', 'version', 'felix-build.json',
            'we-proton-build-info', 'felix/local-beta.py')
MAX_UNPACKED = 2 * 1024**3


class SetupError(Exception):
    pass


def _hash(stream):
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(512 * 1024), b''):
        digest.update(chunk)
    return digest.hexdigest()


def inspect_installer(path):
    """Check local x86 Windows executable format, returning path and SHA-256."""
    if path is None:
        return None, None
    p = Path(path).expanduser()
    if p.suffix.lower() != '.exe' or not p.is_file():
        raise SetupError('请选择已从网易 UU 官方下载的本地 Windows 安装程序（.exe）。')
    try:
        with p.open('rb') as f:
            head = f.read(64)
            if len(head) != 64 or head[:2] != b'MZ':
                raise ValueError()
            offset = struct.unpack_from('<I', head, 60)[0]
            if not 64 <= offset <= 1024**2:
                raise ValueError()
            f.seek(offset)
            coff = f.read(26)
            if len(coff) != 26 or coff[:4] != b'PE\0\0':
                raise ValueError()
            machine, sections = struct.unpack_from('<HH', coff, 4)
            optional_size, flags, magic = struct.unpack_from('<HHH', coff, 20)
            if (not 1 <= sections <= 96 or optional_size < 2 or
                    (machine, magic) not in ((0x14c, 0x10b), (0x8664, 0x20b)) or
                    not flags & 2 or flags & 0x2000 or
                    offset + 24 + optional_size + 40 * sections > os.fstat(f.fileno()).st_size):
                raise ValueError()
            f.seek(0)
            return str(p.resolve(strict=True)), _hash(f)
    except (OSError, ValueError, struct.error) as e:
        raise SetupError('所选文件不是可读的 x86/x64 Windows PE 安装程序。') from e


def _native_root(home, explicit):
    data = os.environ.get('XDG_DATA_HOME')
    candidates = ([Path(explicit).expanduser()] if explicit else
                  [home/'.steam/root', home/'.steam/steam',
                   (Path(data) if data and Path(data).is_absolute() else home/'.local/share')/'Steam',
                   home/'.local/share/Steam', home/'.steam/debian-installation'])
    for root in candidates:
        try:
            resolved = root.resolve()
            if ('.var' in resolved.parts or 'snap' in resolved.parts) and not explicit:
                continue
            if (resolved/'steam.sh').is_file() and (resolved/'steamapps').is_dir():
                if any(seq in str(resolved) + '/' for seq in ('/.var/app/com.valvesoftware.Steam/', '/snap/steam/')):
                    continue
                return resolved
        except (OSError, RuntimeError):
            continue
    return None


def _find(explicit, defaults, flags=()):
    for candidate in ([explicit] if explicit is not None else defaults):
        if not candidate:
            continue
        p = Path(candidate).expanduser().absolute()
        if not p.is_file() or not os.access(p, os.X_OK):
            continue
        if flags:
            try:
                res = subprocess.run([p, '--help'], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, timeout=4, env={**os.environ, 'LC_ALL':'C'})
            except (OSError, subprocess.TimeoutExpired):
                continue
            if not all(re.search(rb'(?<![\w-])'+re.escape(f)+rb'(?![\w-])', res.stdout) for f in flags):
                continue
        return str(p)
    return None


def discover(*, steam_root=None, wrapper=None, pasta=None, steam=None, uu_installer=None, home=None):
    """Read-only readiness report, without initializing a prefix or namespace."""
    home = Path.home() if home is None else Path(home)
    root = _native_root(home, steam_root)
    issues, warnings = [], []
    if sys.platform != 'linux' or os.uname().machine not in ('x86_64', 'amd64'):
        issues.append('此运行器需要 x86-64 Linux。')
    if not Path('/dev/net/tun').is_char_device() or not os.access('/dev/net/tun', os.R_OK | os.W_OK):
        issues.append('当前用户无法访问 /dev/net/tun，请检查系统的 TUN 支持。')
    for key in ('/proc/sys/user/max_user_namespaces', '/proc/sys/kernel/unprivileged_userns_clone'):
        try:
            if Path(key).read_text().strip() == '0':
                issues.append('当前系统禁止新建非特权用户命名空间，请先由系统管理员检查。')
                break
        except OSError:
            pass
    wrap = _find(wrapper, [shutil.which('shorin-proton-wrapper'), home/'.local/bin/shorin-proton-wrapper'],
                 (b'--netns', b'--prefix', b'--runner'))
    past = _find(pasta, [shutil.which('pasta'), home/'.local/bin/pasta', home/'.local/lib/uu-accelerator/bin/pasta'],
                 (b'--config-net', b'--ns-mac-addr', b'--no-pidns'))
    if past and Path(past).name != 'pasta':
        past = None  # the wrapper always looks up a program named pasta on PATH
    # Prioritize the native distro launcher over possible custom PATH gates.
    native = _find(steam, ['/usr/bin/steam', '/usr/games/steam', shutil.which('steam')])
    if native and (Path(native).resolve().name in ('flatpak','snap','uu-network-steam','local-beta.py') or
                   any(s in path for s in ('/snap/bin/', '/flatpak/exports/', '/.local/lib/uu-accelerator/')
                       for path in (native, str(Path(native).resolve())))):
        native = None
    if not root:
        issues.append('未找到已初始化的 Linux 原生 Steam。请先打开它一次，也可指定 --steam-root。')
    if not native:
        issues.append('未找到原生 Steam 可执行入口，请指定 --steam。')
    if not wrap:
        issues.append('缺少支持 --netns、--prefix 和 --runner 的 shorin-proton-wrapper，可用 --wrapper 指定。')
    if not past:
        issues.append('缺少试用版验证过的 pasta 功能（包括 --no-pidns）。可用 --pasta 指向合适版本。')
    for tool in ('zstd','bash','flock','nsenter','unshare'):
        if not shutil.which(tool):
            issues.append('缺少系统工具 ' + tool + '。')
    if Path('/proc/sys/kernel/apparmor_restrict_unprivileged_userns').is_file():
        try:
            if Path('/proc/sys/kernel/apparmor_restrict_unprivileged_userns').read_text().strip() == '1':
                warnings.append('系统对用户命名空间启用了 AppArmor 限制。程序存在性检查不能保证启动成功，首次运行会检验当前策略。')
        except OSError:
            pass
    installer = installer_sha = None
    try:
        installer, installer_sha = inspect_installer(uu_installer)
    except SetupError as exc:
        issues.append(str(exc))
    target = root/'compatibilitytools.d'/TOOL if root else None
    return dict(ready=not issues, issues=issues, warnings=warnings,
                runner_dir=str(target) if target else None, runner=str(target/'proton') if target else None,
                steam_root=str(root) if root else None, wrapper=wrap,
                pasta_bin_dir=str(Path(past).parent) if past else None, steam_real=native,
                uu_installer=installer, uu_installer_sha256=installer_sha)


def _rename_new(source, target):
    libc = ctypes.CDLL(None, use_errno=True)
    if not hasattr(libc, 'renameat2'):
        raise SetupError('系统缺少无覆盖的原子目录安装操作 renameat2。')
    if libc.renameat2(-100, os.fsencode(source), -100, os.fsencode(target), 1):  # RENAME_NOREPLACE
        code = ctypes.get_errno()
        if code == errno.EEXIST:
            raise SetupError('目标目录刚被其他程序创建；请重新运行以核对其内容。')
        raise OSError(code, os.strerror(code))


def _visit(archive, dest, existing):
    # The archive is pinned by SHA-256; additionally accept only the exact tiny
    # subset of tar used by the historical packager. Never extract through a symlink.
    seen = {}
    links = []
    total = 0
    with subprocess.Popen([shutil.which('zstd') or 'zstd', '-qdc'], stdin=archive, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL) as proc:
        try:
            with proc.stdout as pipe, tarfile.open(fileobj=pipe, mode='r|') as members:
                for member in members:
                    name = member.name
                    parts = name.split('/')
                    if (parts[0] != TOOL or any(p in ('', '.', '..') for p in parts) or
                            name in seen or len(seen) >= 15000 or member.mode & 0o7000):
                        raise SetupError('归档含重复、越界或不支持的成员。')
                    if len(parts) > 1 and seen.get('/'.join(parts[:-1])) != 'dir':
                        raise SetupError('归档成员的父级不是已声明的普通目录。')
                    path = dest.joinpath(*parts[1:])
                    if member.isdir():
                        seen[name] = 'dir'
                        if existing:
                            if path.is_symlink() or not path.is_dir():
                                raise SetupError('现有目标目录的布局与试用包不符。')
                        elif len(parts) > 1:
                            path.mkdir(mode=0o755)
                    elif member.issym():
                        seen[name] = 'link'
                        target = member.linkname
                        norm = posixpath.normpath(posixpath.join(posixpath.dirname(name), target))
                        if not target or target.startswith('/') or not norm.startswith(TOOL+'/'):
                            raise SetupError('归档含越界符号链接。')
                        if existing:
                            if not path.is_symlink() or os.readlink(path) != target:
                                raise SetupError('现有目标的符号链接与试用包不符。')
                        else:
                            path.symlink_to(target)
                        links.append(path)
                    elif member.isfile() and member.type in (tarfile.REGTYPE, tarfile.AREGTYPE):
                        seen[name] = 'file'
                        total += member.size
                        if total > MAX_UNPACKED or member.size < 0:
                            raise SetupError('归档超出本版本的体积限制。')
                        body = members.extractfile(member)
                        with body:
                            if existing:
                                if (path.is_symlink() or not path.is_file() or path.stat().st_size != member.size or
                                        (path.stat().st_mode & 0o111) != (member.mode & 0o111)):
                                    raise SetupError('现有目标的文件与试用包不符。')
                                with path.open('rb') as f:
                                    if _hash(f) != _hash(body):
                                        raise SetupError('现有目标的文件内容已改变，将保留现状。')
                            else:
                                with path.open('xb') as f:
                                    shutil.copyfileobj(body, f, length=512*1024)
                                path.chmod(member.mode & 0o777)
                    else:
                        raise SetupError('归档含不支持的成员类型。')
                # GNU tar pads output with zeros; drain the verified decoder.
                while pipe.read(65536):
                    pass
            if proc.wait():
                raise SetupError('zstd 解压失败。')
        except BaseException:
            proc.kill()
            raise
    if not all(seen.get(TOOL+'/'+n) == 'file' for n in REQUIRED):
        raise SetupError('归档缺少运行器或试用版入口。')
    if any(not p.resolve(strict=True).is_relative_to(dest) for p in links):
        raise SetupError('归档中有断开的链接或链接最终指向目录外。')
    return seen


def _verify_existing(dest, seen):
    # Runtime-generated bytecode can appear after use. Other additions could
    # shadow a module or change Proton behavior: keep the directory and refuse.
    for parent, dirs, files in os.walk(dest, followlinks=False):
        for name in dirs + files:
            p = Path(parent)/name
            if (TOOL+'/'+str(p.relative_to(dest))) in seen:
                continue
            if name == '__pycache__' and p.is_dir() and not p.is_symlink():
                continue
            if (p.parent.name == '__pycache__' and p.suffix == '.pyc'
                    and p.is_file() and not p.is_symlink()):
                continue
            raise SetupError('目标中有试用包之外的文件。已保留目录，请先检查冲突。')


def install_runner(archive, steam_root):
    target = Path(steam_root).resolve()/'compatibilitytools.d'/TOOL
    with os.fdopen(os.open(Path(archive).expanduser(), os.O_RDONLY | os.O_NONBLOCK), 'rb') as f:
        before = os.fstat(f.fileno())
        if not stat.S_ISREG(before.st_mode) or _hash(f) != SHA256:
            raise SetupError('运行器归档 SHA-256 与 0.1.0-test.1 不符。')
        f.seek(0)
        parent = target.parent
        parent.mkdir(mode=0o755, exist_ok=True)
        if parent.is_symlink() or not parent.is_dir():
            raise SetupError('compatibilitytools.d 必须是 Steam 根目录内的普通目录。')
        dfd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            fcntl.flock(dfd, fcntl.LOCK_EX)
            if target.is_symlink():
                raise SetupError('目标运行器是符号链接，请先检查。')
            existing = target.exists()
            if existing and not target.is_dir():
                raise SetupError('目标路径已存在且不是目录。')
            if not existing and shutil.disk_usage(parent).free < MAX_UNPACKED:
                raise SetupError('安装运行器需要至少 2 GiB 临时可用空间。')
            with (contextlib.nullcontext(str(target)) if existing else
                  tempfile.TemporaryDirectory(prefix='.felix-stage-', dir=parent)) as staging_name:
                dest = Path(staging_name)
                seen = _visit(f, dest, existing)
                after = os.fstat(f.fileno())
                if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                    raise SetupError('校验后归档被修改，请重新选择文件。')
                if existing:
                    _verify_existing(target, seen)
                else:
                    dest.chmod(0o755)
                    _rename_new(dest, target)
                    os.fsync(dfd)
        finally:
            os.close(dfd)
    return 'existing' if existing else 'installed'


def prepare(archive, *, steam_root=None, wrapper=None, pasta=None, steam=None, uu_installer=None, home=None):
    report = discover(steam_root=steam_root, wrapper=wrapper, pasta=pasta, steam=steam, uu_installer=uu_installer, home=home)
    if not report['ready']:
        raise SetupError('\n'.join(report['issues']))
    try:
        report['install_status'] = install_runner(archive, report['steam_root'])
    except (OSError, RuntimeError, tarfile.TarError) as e:
        raise SetupError('读取、核对或安装运行器失败：'+str(e)) from e
    return report


def main():
    ap = argparse.ArgumentParser(description='检查本机环境并安装已校验的 Felix UU 测试运行器。')
    ap.add_argument('--check', action='store_true', help='仅检查依赖和可选的 UU 安装包')
    ap.add_argument('--json', action='store_true', help='以 JSON 输出结果')
    ap.add_argument('--archive', type=Path, default=Path(__file__).resolve().with_name(ARCHIVE))
    for key in ('steam-root','wrapper','pasta','steam','uu-installer'):
        ap.add_argument('--'+key, type=Path)
    a = ap.parse_args()
    args = {k:getattr(a,k) for k in ('steam_root','wrapper','pasta','steam','uu_installer')}
    try:
        report = discover(**args) if a.check else prepare(a.archive, **args)
    except SetupError as e:
        print(json.dumps({'ready':False,'issues':[str(e)]},ensure_ascii=False) if a.json else str(e),file=sys.stderr)
        return 1
    if a.json:
        print(json.dumps(report,ensure_ascii=False))
    else:
        for text in (*report['issues'], *report['warnings']):
            print(text)
        if report['ready']:
            print('依赖检查通过。' if a.check else '已校验运行器：'+report['runner_dir'])
    return 0 if report['ready'] else 1


if __name__ == '__main__':
    sys.exit(main())
