#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""The existing desktop entries launch exactly the selected application."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

sys.dont_write_bytecode = True
OVERRIDES = ('UU_NETWORK_CONFIG','UU_PREFIX','UU_RUNNER','UU_WRAPPER','UU_EXE',
             'UU_PASTA_BIN_DIR','UU_LOCALE','UU_DESKTOP_WRAPPER','STEAM_REAL')


def active_file():
    return Path(os.environ.get('XDG_CONFIG_HOME') or Path.home()/'.config')/'felix-native-ux/active.json'


def load(config=None):
    if config is None:
        active = json.loads(active_file().read_text())
        if set(active) != {'config'} or not Path(active['config']).is_absolute():
            raise ValueError('未找到有效的 UU 网络配置。')
        config = Path(active['config'])
    cfg = json.loads(config.read_text())
    root = Path(cfg['runner']).expanduser().parent.resolve()
    prefix = Path(cfg['prefix']).expanduser().resolve()
    felix = root/'felix'
    client = Path(cfg.get('uu_executable',prefix/'pfx/drive_c/Program Files (x86)/Netease/UU/uu_launcher.exe')).expanduser()
    return SimpleNamespace(config=config, prefix=prefix, stable=Path.home()/'Games/UU-Accelerator',
                           root=root, observer=felix/'observe.py', portable=felix/'launchers', client=client)


def state(ctx):
    path = ctx.root/'felix/local-beta.py'
    spec=importlib.util.spec_from_file_location('felix_runtime_state',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.session_state(ctx)


def command(ctx, mode, args):
    entry = 'uu-network-steam' if mode=='steam' else 'uu-network-launch'
    env = os.environ.copy()
    for name in OVERRIDES:
        env.pop(name, None)
    env['UU_NETWORK_CONFIG']=str(ctx.config)
    if mode != 'steam':
        env.update(PROTON_USE_XALIA='0', PROTON_USE_WOW64='1', PROTON_NO_FSYNC='1', PROTON_DESKTOP_IMPORT='0')
    argv=[sys.executable, str(ctx.observer), 'exec','--prefix',str(ctx.prefix),'--action',mode,
          '--',str(ctx.portable/entry),*args]
    return argv,env



def prime_control_route(ctx):
    if os.environ.get('FELIX_STEAM_CM_GUARD')=='0':
        return
    try:
        from cm_guard import ensure
        ensure(ctx)
    except Exception:
        # Keep the application's existing launch behavior available if this
        # optional protection cannot be prepared on a particular machine.
        try:
            subprocess.run(['notify-send','Steam 连接保护',
                            '连接保护暂未就绪，Steam 仍按原方式启动。可在停止 UU 加速后重试。'],
                           stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=2,check=False)
        except (OSError,subprocess.TimeoutExpired):
            pass


def dispatch(ctx, mode, args):
    if not ctx.client.is_file() and (mode=='uu' or not (ctx.prefix/'pfx/system.reg').is_file()):
        raise ValueError('此环境尚未初始化完整，请重新运行安装程序。')
    if mode == 'uu' and args:
        raise ValueError('普通 UU 图标无需附加启动参数。')
    status=state(ctx)
    if status.get('conflict'):
        # A running client outside the target network cannot be moved by invoking its desktop file.
        try:
            subprocess.run([sys.executable,str(ctx.observer),'mark','--prefix',str(ctx.prefix),
                            '--event','launch-refused','--reason',status.get('reason') or 'wrong-network'],
                           stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5,check=False)
        except (OSError,subprocess.TimeoutExpired):
            pass
        if status.get('reason')=='wrong-network' and status.get('native_steam_count'):
            raise ValueError('Steam 已在另一网络运行。请在 Steam 菜单正常退出，再从平时的 Steam 图标打开。')
        raise ValueError(status['conflict'].replace('测试版','此'))
    # Whichever app starts first opens the per-prefix network. Startup serialization
    # and the Wine/native join path belong to shorin-proton-wrapper.
    if not (mode=='steam' and '-shutdown' in args):
        prime_control_route(ctx)
    warm_click = (mode=='steam' and not args and status.get('native_steam_count',0)>0
                  and status.get('beta_network'))
    argv,env=command(ctx,mode,['steam://open/games'] if warm_click else args)
    if warm_click:
        # Steam's empty single-instance request can succeed while the existing
        # sign-in dialog remains behind another app. Keep the observed launch
        # and the protected Steam entry as the fallback for a tray-only client.
        at = argv.index('--') + 1
        argv[at:at] = [sys.executable, str(Path(__file__).resolve().with_name('steam_window.py')),
                        status['beta_network']]
    os.execve(sys.executable,argv,env)


def main():
    if len(sys.argv)<2 or sys.argv[1] not in ('uu','steam','status'):
        print('参数为 uu、steam 或 status。',file=sys.stderr)
        return 2
    try:
        ctx=load()
        if sys.argv[1]=='status':
            print(json.dumps(state(ctx),ensure_ascii=False))
            return 0
        dispatch(ctx,sys.argv[1],sys.argv[2:])
    except Exception as error:
        msg=str(error)
        print('UU 与 Steam：'+msg,file=sys.stderr)
        try:
            subprocess.run(['notify-send','网易 UU 与 Steam',msg],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                           timeout=3,check=False)
        except (OSError,subprocess.TimeoutExpired):
            pass
        return 1


if __name__=='__main__':
    raise SystemExit(main())
