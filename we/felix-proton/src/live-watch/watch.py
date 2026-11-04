#!/usr/bin/env python3
"""Bounded, private, passive monitor for one live game-acceleration test."""
from datetime import datetime
import importlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import sys
import time

sys.dont_write_bytecode=True
folder=Path(sys.argv[1])
prefix=Path(sys.argv[2]).resolve()
runner=Path(sys.argv[3]).resolve()
sys.path.insert(0,str(runner/'felix'))
from net_beta import snapshot
start=time.monotonic()
stop=False
plugins={}
latest={}
last_net=None
last_games=None
last_heartbeat=0
game_tick=0
kernel_buf=b''
sequence=0


def end(*_):
    global stop
    stop=True


def at():
    return datetime.now().astimezone().isoformat(timespec='milliseconds')


def write(row, alert=False):
    global sequence
    sequence+=1
    row={'at':at(),'monotonic_s':round(time.monotonic(),3),'sequence':sequence,**row}
    for name in ('timeline.jsonl','alerts.jsonl') if alert else ('timeline.jsonl',):
        p=folder/name
        if p.exists() and p.stat().st_size>8*1024*1024:
            p.replace(folder/(name+'.previous'))
        with os.fdopen(os.open(p,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600),'a') as out:
            out.write(json.dumps(row,ensure_ascii=False)+'\n')
            out.flush();os.fsync(out.fileno())


def health():
    mem={}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key,_,value=line.partition(':')
        if key in ('MemAvailable','SwapFree'):mem[key]=int(value.split()[0])
    psi={}
    for name in ('cpu','memory','io'):
        try:
            text=Path('/proc/pressure',name).read_text().splitlines()[0]
            psi[name]=float(re.search(r'avg10=([0-9.]+)',text)[1])
        except (OSError,TypeError,ValueError):pass
    return {'type':'system_sample','memory_kib':mem,'pressure_avg10':psi,'load':list(os.getloadavg())}


def plugin(name):
    if name in plugins:return plugins[name]
    if not Path(__file__).with_name(name+'.py').is_file():return None
    try:
        mod=importlib.import_module(name)
        obj=(mod.SteamEvents(Path.home()/'.steam/root/logs') if name=='steam_events'
             else mod.GameRoutes(prefix,Path.home()/'.steam/root/logs'))
    except Exception as err:
        write({'type':'coverage_gap','component':name,'error_class':type(err).__name__},True)
        return None
    plugins[name]=obj
    write({'type':'coverage_started','component':name},True)
    if hasattr(obj,'snapshot'):
        latest['steam']=obj.snapshot()
        write({'type':'steam_initial_state','state':latest['steam']},True)
    return obj


signal.signal(signal.SIGTERM,end)
signal.signal(signal.SIGINT,end)
boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
write({'type':'watch_started','boot_id':boot,'duration_limit_s':14400},True)
kernel=None
selector=selectors.DefaultSelector()
try:
    kernel=subprocess.Popen(['journalctl','-k','-b','--since','now','--no-pager','-f','-o','json'],
                            stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    os.set_blocking(kernel.stdout.fileno(),False)
    selector.register(kernel.stdout,selectors.EVENT_READ)
except OSError:
    write({'type':'coverage_gap','component':'kernel'},True)

try:
 while not stop and time.monotonic()-start<14400:
    begin=time.monotonic()
    try:
        net=snapshot(prefix)
        logical={k:v for k,v in net.items() if k not in ('uu_rx_bytes','uu_tx_bytes')}
        if logical!=last_net or begin-last_heartbeat>=15:
            write({'type':'network_sample',**net},logical!=last_net)
            last_net=logical;last_heartbeat=begin
        latest['network']=net
        ste=plugin('steam_events')
        if ste:
            for event in ste.poll():
                typ=event.get('type','')
                quiet=('rate' in typ or typ in ('log_growth','source_baseline'))
                write({'component':'steam',**event},not quiet)
                latest['last_steam_event']=event
            if hasattr(ste,'snapshot'):latest['steam']=ste.snapshot()
        if begin-game_tick>=5:
            game_tick=begin
            gr=plugin('game_routes')
            if gr:
                games=gr.poll()
                if games!=last_games:
                    write({'type':'game_route_sample',**games},True)
                    last_games=games
                latest['games']=games
        if int(begin-start)//10!=int(latest.get('last_health',-1))//10:
            write(health())
            latest['last_health']=begin-start
        if kernel:
            for key,_ in selector.select(0):
                try:kernel_buf+=os.read(key.fileobj.fileno(),131072)
                except BlockingIOError:pass
            lines=kernel_buf.split(b'\n');kernel_buf=lines.pop()[-131072:]
            for line in lines:
                try:entry=json.loads(line)
                except ValueError:continue
                msg=entry.get('MESSAGE','')
                kind=next((name for name,pattern in (
                    ('timer_workqueue',r'WARNING: kernel/workqueue|general protection fault.*|RIP:.*__run_timers'),
                    ('kernel_panic',r'Kernel panic|Fatal exception in interrupt'),
                    ('gpu_error',r'NVRM: Xid|GPU HANG|GPU.*reset failed'),
                    ('out_of_memory',r'Out of memory|oom-kill:'),
                    ('io_error',r'I/O error, dev|nvme.*(?:reset|timeout)'),
                    ('lockup',r'soft lockup|hard LOCKUP|blocked for more than'))
                    if re.search(pattern,msg,re.I)),None)
                if kind:write({'type':'kernel_signal','signal':kind},True)
        latest.update(at=at(),uptime_s=round(time.monotonic()-start,1))
        tmp=folder/'summary.tmp'
        with tmp.open('w') as out:
            json.dump(latest,out,ensure_ascii=False);out.flush();os.fsync(out.fileno())
        tmp.replace(folder/'summary.json')
    except Exception as err:
        write({'type':'poll_gap','error_class':type(err).__name__},True)
    delay=max(.05,2-(time.monotonic()-begin))
    deadline=time.monotonic()+delay
    while not stop and time.monotonic()<deadline:
        time.sleep(min(.2,max(0,deadline-time.monotonic())))
finally:
    write({'type':'watch_stopped','reason':'requested' if stop else 'duration_limit'},True)
    selector.close()
    if kernel and kernel.poll() is None:
        kernel.terminate()
        try:kernel.wait(timeout=2)
        except subprocess.TimeoutExpired:kernel.kill();kernel.wait()
