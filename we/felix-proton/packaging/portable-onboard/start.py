#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Install a single, user-scoped entry for the verified Felix UU test runner."""
import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
if sys.version_info < (3, 10):
    sys.exit('本次预览需 Python 3.10 或更新版本。')
import bootstrap
from beta_base import Beta, Refused, create_only, quoted_desktop_path, read_json
from pair_session import launch_pair

VERSION = 'preview1'
FILES = ('start.py', 'bootstrap.py', 'pair_session.py', 'beta_base.py')


def personal(base, fallback):
    return Path(os.environ.get(base) or (Path.home() / fallback)) / 'felix-uu-portal' / VERSION


def libdir():
    return personal('XDG_DATA_HOME', '.local/share')


def cfgdir():
    return personal('XDG_CONFIG_HOME', '.config')


def strict_copy(name, dest, data, mode=0o600):
    if dest.is_symlink():
        raise Refused(f'{name}指向其他位置，请检查。')
    try:
        create_only(dest, data, mode)
    except FileExistsError:
        if not dest.is_file() or dest.read_bytes() != data:
            raise Refused(f'{name}已存在且内容不同，原文件保留。')


def notice(msg, error=False):
    print(msg, file=sys.stderr if error else sys.stdout)
    if not sys.stderr.isatty() and os.environ.get('DISPLAY', os.environ.get('WAYLAND_DISPLAY')):
        try:
            subprocess.run(['notify-send', '-a', 'Felix UU', 'UU 游戏加速', msg],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            pass


def choose_installer():
    prompt = '请选择从网易 UU 官网下载的 Windows 安装程序'
    if (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')) and shutil.which('zenity'):
        res = subprocess.run(['zenity','--file-selection','--title='+prompt,
                              '--file-filter=Windows 安装程序 | *.exe *.EXE'], capture_output=True, text=True)
        if res.returncode:
            return None
        path = res.stdout.rstrip('\n')
    elif sys.stdin.isatty():
        path = input(prompt + '，输入路径（回车取消）：').strip()
    else:
        raise Refused('需要选择 UU 安装文件。请安装 zenity，或在终端运行 python3 start.py open --uu-installer 文件路径。')
    if not path:
        return None
    return Path(bootstrap.inspect_installer(path)[0])


class Portal(Beta):
    def __init__(self, choices):
        self.steam_root = Path(choices['steam_root'])
        super().__init__(root=self.steam_root/'compatibilitytools.d'/bootstrap.TOOL)
        self.choices = choices
        # A fresh portal prefix has no legacy launcher ownership records or login data.
        self.prefix = self.home / 'Games/Felix-UU-Portal-preview1'
        self.config = cfgdir()/'config.json'
        self.manifest = cfgdir()/'owned-files.json'
        self.marker = self.prefix/'.felix-uu-test-owner'
        self.network_config = self.prefix/'.shorin-proton-wrapper.conf'
        self.client = self.prefix/'pfx/drive_c/Program Files (x86)/Netease/UU/uu_launcher.exe'

    def config_defaults(self):
        return {'prefix':str(self.prefix), 'runner':str(self.runner), 'wrapper':self.choices['wrapper'],
                'steam_real':self.choices['steam_real'], 'pasta_bin_dir':self.choices['pasta_bin_dir'],
                'uu_executable':str(self.client)}

    def desktop_files(self):
        script = quoted_desktop_path(libdir()/'start.py')
        content = ('[Desktop Entry]\nType=Application\nName=UU 游戏加速（Steam）\n'
                   'Comment=在同一个测试网络打开网易 UU 和原生 Steam\n'
                   f'Exec=/usr/bin/python3 {script} open\n'
                   'Icon=network-vpn\nTerminal=false\nCategories=Game;Network;\nStartupNotify=false\n'
                   'Actions=Mark;\n\n[Desktop Action Mark]\nName=标记刚才异常\n'
                   f'Exec=/usr/bin/python3 {script} mark\n')
        return {self.apps/'felix-uu-portal-preview1.desktop':content.encode()}


@contextlib.contextmanager
def portal_lock():
    private = cfgdir()
    private.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (private/'.portal-lock').open('a') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Refused('统一入口正在准备 UU 或 Steam，请稍候。') from None
        yield


def save_choices(choices):
    path = cfgdir()/'paths.json'
    with tempfile.NamedTemporaryFile(dir=cfgdir(), delete=False) as f:
        f.write((json.dumps(choices,ensure_ascii=False,indent=2)+'\n').encode())
        tmp = Path(f.name)
    try:
        os.replace(tmp,path)
    finally:
        tmp.unlink(missing_ok=True)


def install(args):
    source = Path(__file__).resolve().parent
    locations = (source, source.parent, Path.home()/'Downloads')
    archive = args.archive or next((d/bootstrap.ARCHIVE for d in locations if (d/bootstrap.ARCHIVE).is_file()), None)
    if archive is None or not archive.is_file():
        raise Refused('请把 test.1 的 .tar.zst 运行器包放到 start.py 旁边或下载目录（无需解压），再重新运行。')
    with portal_lock():
        report = bootstrap.prepare(archive, **opts(args))
        choices = {key:report[key] for key in ('steam_root','steam_real','wrapper','pasta_bin_dir',
                                                'uu_installer','uu_installer_sha256') if key in report}
        portal = Portal(choices)
        target = libdir()
        target.mkdir(mode=0o700, parents=True,exist_ok=True)
        if target.is_symlink():
            raise Refused('向导安装目录指向其他位置，请检查。')
        for name in FILES:
            strict_copy(name,target/name,(source/name).read_bytes())
        # Preserve personal edits on rerun. The saved choices locate the installed runner.
        portal.install()
        save_choices(choices)
    return '\n'.join(['已创建「UU 游戏加速（Steam）」。第一次打开时按提示完成 UU 安装并登录。', *report.get('warnings', [])])


def opts(args):
    return {k:getattr(args,k,None) for k in ('steam_root','wrapper','pasta','steam','uu_installer')}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Felix UU 统一试用入口')
    parser.add_argument('action',nargs='?',choices=['check','install','open','mark','remove'],default='install')
    parser.add_argument('--archive',type=Path)
    parser.add_argument('--uu-installer',type=Path,help='从网易官方下载的 Windows 安装程序')
    for flag in ('steam-root','steam','wrapper','pasta'):
        parser.add_argument('--'+flag)
    args=parser.parse_args(argv)
    try:
        if args.action=='check':
            report=bootstrap.discover(**opts(args))
            text='\n'.join(report['issues']+report['warnings'])
            print(('基础依赖已找到。' if report['ready'] else '请先处理以下依赖。')+('\n'+text if text else ''))
            return 0 if report['ready'] else 1
        if args.action=='install':
            notice(install(args))
            return 0
        if not (cfgdir()/'paths.json').is_file():
            raise Refused('请先在解压后的引导器目录运行 python3 start.py。')
        choices=read_json(cfgdir()/'paths.json')
        beta=Portal(choices)
        if args.action=='mark':
            beta.mark_issue()
            return 0
        with portal_lock():
            if args.action=='remove':
                notice(beta.uninstall())
            else:
                selected = args.uu_installer or choices.get('uu_installer')
                if selected and args.uu_installer:
                    selected = bootstrap.inspect_installer(selected)[0]
                elif selected and not beta.client.is_file():
                    if not Path(selected).is_file():
                        selected = None
                    else:
                        selected, actual = bootstrap.inspect_installer(selected)
                        if choices.get('uu_installer_sha256')!=actual:
                            raise Refused('此前选择的安装文件已改变，请重新选择官方安装文件。')
                notice(launch_pair(beta, choose_installer, installer=selected))
        return 0
    except (Refused,bootstrap.SetupError,RuntimeError,OSError,ValueError,KeyError) as e:
        notice(str(e),error=True)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
