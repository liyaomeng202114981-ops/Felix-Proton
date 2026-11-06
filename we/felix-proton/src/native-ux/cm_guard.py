#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Keep Steam CM TCP endpoints on an owned, namespace-local stable route."""
import contextlib
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys
import tempfile
import time
import threading

sys.dont_write_bytecode=True
STOP=False
STATUS_HEARTBEAT=5


def _stop(*_):
    global STOP
    STOP=True


def _private_file(path, data):
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent,delete=False) as f:
        temporary=Path(f.name)
        f.write((json.dumps(data,ensure_ascii=False)+'\n').encode())
        f.flush();os.fsync(f.fileno())
    try:os.replace(temporary,path)
    finally:temporary.unlink(missing_ok=True)


def _paths(ctx):
    key=hashlib.sha256(os.fsencode(ctx.prefix.resolve())).hexdigest()[:16]
    runtime=Path(os.environ.get('XDG_RUNTIME_DIR') or f'/tmp/shorin-proton-wrapper-{os.getuid()}')
    state=Path(os.environ.get('XDG_STATE_HOME') or Path.home()/'.local/state')
    return runtime/'felix-steam-cm'/key,state/'felix-steam-cm'/key


def _net_module(ctx):
    if str(ctx.root/'felix') not in sys.path:sys.path.insert(0,str(ctx.root/'felix'))
    import net_beta
    return net_beta


def _keeper(ctx):
    net=_net_module(ctx)
    runtime=Path(os.environ.get('XDG_RUNTIME_DIR') or f'/tmp/shorin-proton-wrapper-{os.getuid()}')
    key=hashlib.sha256(os.fsencode(ctx.prefix.resolve())).hexdigest()[:16]
    return net._keeper(Path('/proc'),runtime/'shorin-proton-wrapper/sessions'/key,os.getuid())


def _alive(meta, ctx):
    try:
        p=Path('/proc')/str(meta['pid'])
        return (p.stat().st_uid==os.getuid()
                and (p/'stat').read_bytes().rsplit(b') ',1)[1].split()[19].decode()==meta['start']
                and (p/'cmdline').read_bytes().split(b'\0')[1:]==[
                    b'-B',os.fsencode(Path(__file__).resolve()),b'_serve',os.fsencode(ctx.config),b''])
    except (OSError,KeyError,IndexError):return False


def _tcp_endpoint(cell, ipv6):
    address, port = cell.split(':')
    if len(address) != (32 if ipv6 else 8) or len(port) != 4:
        raise ValueError('bad_tcp_record')
    # procfs prints each 32-bit network address word in native byte order.
    packed = b''.join(struct.pack('=I', int(address[i:i+8], 16))
                      for i in range(0, len(address), 8))
    address = ipaddress.ip_address(packed)
    if ipv6 and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address, int(port, 16)


def _live(ctx, namespace, *, proc=Path('/proc')):
    """Return native Steam's IPv4 peers, or refuse an incomplete hot takeover."""
    result = []
    for p in proc.iterdir():
        if not p.name.isdecimal():
            continue
        try:
            if (p.stat().st_uid != os.getuid() or (p/'comm').read_bytes() != b'steam\n'
                    or Path(os.readlink(p/'exe')).name != 'steam'
                    or os.readlink(p/'ns/net') != namespace):
                continue
        except OSError:
            continue

        try:
            inodes = set()
            for f in (p/'fd').iterdir():
                try:
                    value = os.readlink(f)
                except FileNotFoundError:
                    continue  # Steam closed this descriptor after the directory scan.
                if value.startswith('socket:['):
                    inodes.add(value[8:-1])
            for name in ('tcp', 'tcp6'):
                rows = (p/'net'/name).read_text().splitlines()
                if not rows or 'local_address' not in rows[0] or 'inode' not in rows[0]:
                    raise ValueError('bad_tcp_table')
                for row in rows[1:]:
                    fields = row.split()
                    if fields[3] not in ('01', '02') or fields[9] not in inodes:
                        continue
                    peer, port = _tcp_endpoint(fields[2], name == 'tcp6')
                    if peer.version == 4 and peer.is_global:
                        local, _ = _tcp_endpoint(fields[1], name == 'tcp6')
                        result.append((str(local), (str(peer), port)))
        except (OSError, IndexError, ValueError, struct.error):
            if p.exists():
                raise RuntimeError('cm_steam_sockets_unreadable') from None
            # The process exited after identification and has no sockets to protect.
    return result


def ensure(ctx):
    """Start once per prefix; no client is terminated or restarted."""
    rt,storage=_paths(ctx)
    rt.mkdir(mode=0o700,parents=True,exist_ok=True)
    with (rt/'startup.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        try:meta=json.loads((rt/'status.json').read_text())
        except (OSError,ValueError):meta={}
        try:current=_keeper(ctx)
        except (OSError,ValueError,IndexError):current=None
        matched=bool(current and meta.get('keeper_pid')==int(current[0].name)
                     and meta.get('keeper_start')==current[1] and meta.get('namespace')==current[2])
        if _alive(meta,ctx) and meta.get('state')=='ready' and matched and time.time()-meta.get('updated',0)<10:
            return meta
        if _alive(meta,ctx) and not matched:
            os.kill(meta['pid'],signal.SIGTERM)
            deadline=time.monotonic()+3
            while _alive(meta,ctx) and time.monotonic()<deadline:time.sleep(.05)
        try:_keeper(ctx)
        except (OSError,ValueError,IndexError):
            # Keep a newly created network alive while endpoint discovery primes.
            cfg=json.loads(ctx.config.read_text())
            env=os.environ.copy()
            for k in ('UU_PREFIX','UU_RUNNER','UU_WRAPPER','STEAM_REAL','UU_PASTA_BIN_DIR','UU_EXE'):
                env.pop(k,None)
            env['UU_NETWORK_CONFIG']=str(ctx.config)
            bridge=subprocess.Popen([str(ctx.portable/'uu-network-run'),'/usr/bin/sleep','25'],
                                    env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL,start_new_session=True)
            threading.Thread(target=bridge.wait,daemon=True).start()
            until=time.monotonic()+7
            while True:
                try:_keeper(ctx);break
                except (OSError,ValueError,IndexError):
                    if bridge.poll() is not None or time.monotonic()>until:
                        raise RuntimeError('cm_network_not_ready')
                    time.sleep(.1)
        if not _alive(meta,ctx):
            daemon=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'_serve',str(ctx.config)],
                                    stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                                    start_new_session=True)
            threading.Thread(target=daemon.wait,daemon=True).start()
        until=time.monotonic()+7
        while time.monotonic()<until:
            try:
                meta=json.loads((rt/'status.json').read_text())
                if _alive(meta,ctx):
                    present=_keeper(ctx)
                    same=(meta.get('keeper_pid')==int(present[0].name) and meta.get('keeper_start')==present[1]
                          and meta.get('namespace')==present[2])
                    if meta.get('state')=='ready' and same:return meta
                    if meta.get('state')=='error':raise RuntimeError(meta.get('error','cm_guard_failed'))
            except (OSError,ValueError):pass
            time.sleep(.1)
        raise RuntimeError('cm_guard_not_ready')


def serve(config):
    import routes
    from policy import Policy,PolicyError
    from endpoints import CMEndpoints
    ctx=routes.load(config)
    rt,storage=_paths(ctx)
    rt.mkdir(mode=0o700,parents=True,exist_ok=True)
    storage.mkdir(mode=0o700,parents=True,exist_ok=True)
    pid=os.getpid();start=(Path('/proc/self/stat').read_bytes().rsplit(b') ',1)[1].split()[19].decode())
    base={'pid':pid,'start':start}
    last_status=None
    last_published=0
    def status(state,**kw):
        nonlocal last_status,last_published
        snapshot={**base,'state':state,**kw}
        now=time.monotonic()
        # Keep the launcher's snapshot fresh without rewriting it every poll.
        if snapshot==last_status and now-last_published<STATUS_HEARTBEAT:
            return
        _private_file(rt/'status.json',{**snapshot,'updated':time.time()})
        last_status,last_published=snapshot,now
    def event(kind,**kw):
        p=storage/'events.jsonl'
        if p.exists() and p.stat().st_size>1024*1024:p.replace(storage/'events.previous.jsonl')
        with os.fdopen(os.open(p,os.O_CREAT|os.O_APPEND|os.O_WRONLY,0o600),'a') as f:
            f.write(json.dumps({'at':time.time(),'type':kind,**kw})+'\n')
            f.flush();os.fsync(f.fileno())
    with (rt/'daemon.lock').open('a') as singleton:
        try:fcntl.flock(singleton,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return
        signal.signal(signal.SIGTERM,_stop);signal.signal(signal.SIGINT,_stop)
        resolver=CMEndpoints(Path.home()/'.steam/root/logs/connection_log.txt',families=(4,))
        policy=None
        try:
            identity=_keeper(ctx); process,_,namespace=identity
            base.update(keeper_pid=int(process.name),keeper_start=identity[1],namespace=namespace)
            with contextlib.ExitStack() as stack:
                handles=[]
                for name in ('user','net'):
                    fd=os.open(process/'ns'/name,os.O_RDONLY);stack.callback(os.close,fd);handles.append(fd)
                if _keeper(ctx)!=identity:raise RuntimeError('keeper_changed')
                ledger=storage/(Path('/proc/sys/kernel/random/boot_id').read_text().strip()+'-'+namespace[5:-1]+'.json')
                policy=stack.enter_context(Policy(*handles,ledger))
                try:
                    policy.capture_baseline()
                    baseline=json.loads(ledger.read_text())['baseline']
                    last=None;last_at=0;primed=time.monotonic()
                    ready_notified=False
                    status('preparing')
                    while not STOP:
                        try:
                            current=_keeper(ctx)
                        except FileNotFoundError:
                            # The wrapper can remove its markers before the keeper exits.
                            break
                        if current!=identity:break
                        live=_live(ctx,namespace)
                        found=resolver.poll(live_tcp=[p for _,p in live])
                        unsafe={p for source,p in live if source!=baseline['source']}
                        wanted=found-unsafe
                        if (wanted or last is not None) and (wanted!=last or time.monotonic()-last_at>15):
                            report=policy.reconcile(wanted)
                            if wanted!=last:event('rules_ready',rules=report['rules'],deferred=len(unsafe))
                            last=wanted;last_at=time.monotonic()
                        if last and ((resolver.status()['directory']=='ok' and len(last)>=4)
                                     or time.monotonic()-primed>=5):
                            status('ready',rules=len(last),directory=resolver.status()['directory'],deferred=len(unsafe))
                            if not ready_notified:
                                ready_notified=True
                                try:
                                    subprocess.run(['notify-send','Steam 连接保护','连接保护已就绪。'],
                                                   stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                                                   timeout=2,check=False)
                                except (OSError,subprocess.TimeoutExpired):
                                    pass
                        elif time.monotonic()-primed>5:
                            status('error',error='cm_endpoints_unavailable')
                        elapsed=time.monotonic()-primed
                        if not ready_notified and elapsed<6:
                            # Consume early lookups promptly, then keep the normal polling cadence.
                            resolver.wait_for_results(.4)
                        else:
                            time.sleep(.4 if elapsed<6 else 2)
                finally:
                    try:
                        policy.rollback()
                        event('rules_removed')
                    except PolicyError as rollback_error:
                        event('rollback_failed',error=str(rollback_error))
                        status('error',error='cm_rollback_failed')
        except (PolicyError,RuntimeError,OSError,ValueError,KeyError,IndexError) as err:
            code=str(err) if isinstance(err,(PolicyError,RuntimeError)) else type(err).__name__
            # No subprocess text, endpoint, account or log line in public status.
            status('error',error=code if len(code)<80 else type(err).__name__)
            event('guard_error',error=code if len(code)<80 else type(err).__name__)
        finally:
            resolver.close()
            event('guard_stopped')
            try:
                now=json.loads((rt/'status.json').read_text())
                if now.get('pid')==pid and now.get('state')!='error':status('stopped')
            except (OSError,ValueError):pass


def main():
    if len(sys.argv)==3 and sys.argv[1]=='_serve':
        return serve(Path(sys.argv[2]))
    import routes
    ctx=routes.load()
    if len(sys.argv)==2 and sys.argv[1]=='status':
        rt,_=_paths(ctx)
        try:print((rt/'status.json').read_text())
        except OSError:print('{"state":"not_running"}')
        return
    if len(sys.argv)==2 and sys.argv[1]=='stop':
        rt,_=_paths(ctx)
        try:
            meta=json.loads((rt/'status.json').read_text())
            if _alive(meta,ctx):os.kill(meta['pid'],signal.SIGTERM)
        except (OSError,ValueError):pass
        return
    print(json.dumps(ensure(ctx)))


if __name__=='__main__':
    main()
