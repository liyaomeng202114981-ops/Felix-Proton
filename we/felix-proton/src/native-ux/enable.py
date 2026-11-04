#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Install or restore the user's normal Steam and UU desktop actions."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True
if sys.version_info < (3,10):
    sys.exit('本地试用包需要 Python 3.10 或更新版本。')
import bootstrap
import desktop
import routes
import setup_config

SOURCES=('policy.py','endpoints.py','cm_guard.py','steam_window.py','desktop.py','setup_config.py','bootstrap.py','routes.py','enable.py')
# Only replace exact files from the previous local preview. Keep personal edits.
PREVIOUS={'routes.py':('31fa095afe768d4f2e8670942c11309e164bfbb9c4b0dabd5eed902a54954926','a2c1679270c1eaebb0d735438889c69a1f02ea02f5be0a2c1d337283ef08d464'),
          'enable.py':('615ee2dfaf94a91d2e3353b2bafdb9125c925435fb425429d7fd17044328bf19','bb8adf6245a99bea9b58ec1bc630c8f147d5585301b0d03bafdb193c2a55e270')}


def xdg(key, fallback):
    path=Path(os.environ.get(key) or Path.home()/fallback)
    return path if path.is_absolute() else Path.home()/fallback


def statedir():
    return xdg('XDG_STATE_HOME','.local/state')/'felix-native-ux'


def libdir():
    return xdg('XDG_DATA_HOME','.local/share')/'felix-native-ux/v1'


@contextlib.contextmanager
def operation():
    d=statedir()
    d.mkdir(mode=0o700,parents=True,exist_ok=True)
    with (d/'.operation').open('a') as handle:
        try:
            fcntl.flock(handle,fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('另一次设置尚未完成。') from None
        yield


def stage_file(path,data,previous=None):
    """Publish complete data, retaining any existing user modifications."""
    if os.path.lexists(path):
        if path.is_symlink() or not path.is_file():
            raise RuntimeError('目标路径不是普通文件，已保留：'+str(path))
        before=path.read_bytes()
        if before==data:
            return
        if previous is None or hashlib.sha256(before).hexdigest() not in ((previous,) if isinstance(previous,str) else previous):
            raise RuntimeError('目标文件已有其他内容，已保留：'+str(path))
        with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as temp:
            tmp=Path(temp.name)
            try:
                temp.write(data)
                temp.flush()
                os.fsync(temp.fileno())
                if path.is_symlink() or path.read_bytes()!=before:
                    raise RuntimeError('更新期间文件发生变化，已保留：'+str(path))
                os.replace(tmp,path)
            finally:
                tmp.unlink(missing_ok=True)
        return
    with tempfile.NamedTemporaryFile(dir=path.parent) as temp:
        temp.write(data)
        temp.flush()
        os.fsync(temp.fileno())
        os.link(temp.name,path)


def select_installer(supplied):
    if supplied:
        return Path(bootstrap.inspect_installer(supplied)[0])
    if shutil.which('zenity') and (os.getenv('DISPLAY') or os.getenv('WAYLAND_DISPLAY')):
        res=subprocess.run(['zenity','--file-selection','--title=首次设置：选择从网易官网下载的 UU 安装程序',
                            '--file-filter=Windows 安装程序 | *.exe *.EXE'],capture_output=True,text=True)
        if res.returncode==0 and res.stdout.rstrip('\n'):
            return Path(bootstrap.inspect_installer(res.stdout.rstrip('\n'))[0])
    raise RuntimeError('首次设置需安装 UU。可重新运行 python3 enable.py --uu-installer "/路径/官方安装包.exe"。')


def ready(ctx):
    return (ctx.prefix/'pfx/system.reg').is_file() and ctx.client.is_file()


def install_uu_if_needed(ctx, supplied):
    if ready(ctx):
        return
    # First-run prefix initialization must happen before native Steam makes a keeper.
    state=routes.state(ctx)
    if state.get('beta_network') or state.get('beta_uu'):
        raise RuntimeError('首次安装需空闲的专用前缀，请先正常退出占用此环境的程序，再重新设置。')
    installer=select_installer(supplied)
    argv,env=routes.command(ctx,'setup',[str(installer)])
    proc=subprocess.Popen(argv,env=env,stdin=subprocess.DEVNULL)
    deadline=time.monotonic()+600
    while time.monotonic()<deadline:
        rc=proc.poll()
        if ready(ctx) and (rc in (0,9) or routes.state(ctx).get('beta_uu')):
            return
        if rc is not None:
            raise RuntimeError(f'安装程序已结束（{rc}），尚未确认客户端安装完成，普通 Steam 入口尚未切换。')
        time.sleep(1)
    raise RuntimeError('安装程序仍在运行，请完成安装并退出，然后重新运行此设置。')


def enable(args):
    source=Path(__file__).resolve().parent
    archive=args.archive or next((p/bootstrap.ARCHIVE for p in (source,source.parent,Path.home()/'Downloads')
                                 if (p/bootstrap.ARCHIVE).is_file()),None)
    config=setup_config.ensure_config(archive,uu_installer=args.uu_installer)
    ctx=routes.load(config)
    install_uu_if_needed(ctx,args.uu_installer)
    d=libdir()
    d.mkdir(parents=True,mode=0o700,exist_ok=True)
    if d.is_symlink():
        raise RuntimeError('辅助程序目录是符号链接，请检查。')
    for name in SOURCES:
        stage_file(d/name,(source/name).read_bytes(),PREVIOUS.get(name))
    active=routes.active_file()
    active.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    stage_file(active,(json.dumps({'config':str(config)},ensure_ascii=False)+'\n').encode())
    return desktop.install(d/'routes.py',statedir())


def refresh():
    cmd=shutil.which('update-desktop-database')
    if cmd:
        subprocess.run([cmd,str(xdg('XDG_DATA_HOME','.local/share')/'applications')],check=False,
                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


def main():
    parser=argparse.ArgumentParser(description='让平时的 Steam 和网易 UU 使用同一网络')
    parser.add_argument('action',nargs='?',default='enable',choices=['enable','restore','status'])
    parser.add_argument('--archive',type=Path)
    parser.add_argument('--uu-installer',type=Path)
    args=parser.parse_args()
    try:
        if args.action=='status':
            print(json.dumps(routes.state(routes.load()),ensure_ascii=False))
            return 0
        with operation():
            result=desktop.restore(statedir()) if args.action=='restore' else enable(args)
            if result.get('changed'):
                refresh()
        print(json.dumps(result,ensure_ascii=False,default=str))
        return 0
    except (OSError,RuntimeError,ValueError,KeyError,bootstrap.SetupError) as e:
        print(str(e),file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
