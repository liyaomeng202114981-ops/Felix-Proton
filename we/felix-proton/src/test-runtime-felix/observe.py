#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Local, bounded, event-only diagnostics for the Felix UU test entrypoints."""
import argparse
import collections
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import select
import shutil
import subprocess
import sys
import time
import uuid

sys.dont_write_bytecode = True
from net_beta import snapshot
from signals_beta import ClientLogTail, classify_line

VERSION = '0.1.0-test.1'
CHANNELS = '-all,+timestamp,+pid,+tid,trace+wintun,warn+wintun,err+wintun,warn+winsock,err+winsock,warn+iphlpapi,err+iphlpapi'
MAX_LOG = 2 * 1024 * 1024
KEEP = 8
IDLE_SECONDS = 90
SESSION_RE = re.compile(r'run-[0-9]{8}T[0-9]{6}-[0-9a-f]{10}')


def store_for(prefix):
    state = Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local/state')
    key = hashlib.sha256(os.fsencode(prefix.resolve())).hexdigest()[:16]
    return state / 'felix-proton-uu' / VERSION / key


def stamp():
    return dt.datetime.now().astimezone().isoformat(timespec='milliseconds')


def append(folder, event):
    """Serialize writers and retain three segments per run, including after rotation."""
    with (folder / '.write').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        p = folder / 'events.jsonl'
        if p.exists() and p.stat().st_size >= MAX_LOG:
            prev = folder / 'events.1.jsonl'
            if prev.exists():
                prev.replace(folder / 'events.2.jsonl')
            p.replace(prev)
        with os.fdopen(os.open(p, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600), 'a') as stream:
            stream.write(json.dumps({**event, 'at': stamp(), 'monotonic_s': round(time.monotonic(), 3)}, ensure_ascii=False)+'\n')


def current(root):
    name = (root / 'latest').read_text().strip()
    if not SESSION_RE.fullmatch(name):
        raise ValueError('Invalid test session ID')
    return root / name


def is_locked(path):
    with path.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
    return False


def ensure_monitor(prefix, lease=False):
    root = store_for(prefix)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / '.startup').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        with (root / '.monitor').open('a') as live:
            try:
                fcntl.flock(live, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                folder = current(root)
            else:
                run_id = dt.datetime.now().strftime('run-%Y%m%dT%H%M%S-') + uuid.uuid4().hex[:10]
                folder = root / run_id
                folder.mkdir(mode=0o700)
                read_fd, ready_fd = os.pipe()
                try:
                    subprocess.Popen([sys.executable, '-B', __file__, '_monitor', str(prefix), str(folder),
                                      str(live.fileno()), str(ready_fd)], pass_fds=(live.fileno(), ready_fd),
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     start_new_session=True)
                    os.close(ready_fd)
                    ready_fd = -1
                    if not select.select([read_fd], [], [], 8)[0] or os.read(read_fd, 1) != b'1':
                        raise RuntimeError('测试记录器未就绪，请检查状态目录与诊断模块。')
                finally:
                    os.close(read_fd)
                    if ready_fd >= 0:
                        os.close(ready_fd)
                pointer = root / '.latest.tmp'
                pointer.write_text(run_id + '\n')
                pointer.replace(root / 'latest')
                older = sorted((p for p in root.iterdir() if SESSION_RE.fullmatch(p.name) and p != folder
                                and p.is_dir() and not p.is_symlink()), key=lambda p: p.stat().st_mtime, reverse=True)
                for obsolete in older[KEEP - 1:]:
                    if not is_locked(obsolete / '.clients'):
                        shutil.rmtree(obsolete)
        token = None
        if lease:
            token = (folder / '.clients').open('a')
            fcntl.flock(token, fcntl.LOCK_SH)
    return folder, token


class SteamTail:
    # Valve writes one line per native Steam tracked process, often several per AppID.
    row = re.compile(rb'\bAppID (\d{1,10}) (adding PID (\d+)|no longer tracking PID \d+, exit code (-?\d{1,10}))')

    def __init__(self):
        self.path = Path.home() / '.steam/root/logs/gameprocess_log.txt'
        self.identity = None
        self.offset = 0
        self.partial = b''
        self.poll(False)

    def poll(self, enabled):
        out = []
        try:
            with self.path.open('rb') as stream:
                st = os.fstat(stream.fileno())
                identity = (st.st_dev, st.st_ino)
                if not enabled:
                    self.identity, self.offset, self.partial = identity, st.st_size, b''
                    return out
                if identity != self.identity or st.st_size < self.offset:
                    self.identity, self.offset, self.partial = identity, 0, b''
                if st.st_size - self.offset > 262144:
                    self.offset, self.partial = st.st_size - 262144, b''
                    stream.seek(self.offset)
                    stream.readline(8192)
                    self.offset = stream.tell()
                    out.append({'type':'steam_log_gap'})
                stream.seek(self.offset)
                buf = stream.read(262144)
                self.offset = stream.tell()
        except OSError:
            return out
        lines = (self.partial + buf).split(b'\n')
        self.partial = lines.pop()[-8192:]
        counts = collections.Counter()
        for line in lines:
            m = self.row.search(line)
            if m:
                counts[(int(m[1]), 'added' if m[3] else 'removed', int(m[4]) if m[4] else None)] += 1
        for (appid, change, code), n in counts.items():
            event = {'type':'steam_game_process', 'appid':appid, 'change':change, 'count':n}
            if code is not None:
                event['exit_code'] = code
            out.append(event)
        return out


def monitor(prefix, folder, live_fd, ready_fd):
    with os.fdopen(live_fd, 'a'):
        logs, games = ClientLogTail(prefix), SteamTail()
        append(folder, {'type':'observer_started', 'build':VERSION})
        os.write(ready_fd, b'1')
        os.close(ready_fd)
        activity = heartbeat = time.monotonic()
        previous = last_fault = None
        while True:
            now = time.monotonic()
            try:
                state = snapshot(prefix)
                summary = {k:v for k,v in state.items() if k not in ('uu_rx_bytes','uu_tx_bytes')}
                if summary != previous or now - heartbeat >= 15:
                    append(folder, {'type':'network_sample', **state})
                    previous, heartbeat = summary, now
                for row in logs.poll():
                    append(folder, {**row, 'source':'uu_client'})
                for row in games.poll(state.get('steam_network') == 'same'):
                    append(folder, {**row, 'source':'steam_gameprocess'})
                last_fault = None
            except Exception as exc:
                # Keep observing through a disappearing client log or namespace.
                if last_fault != type(exc).__name__:
                    append(folder, {'type':'sampling_gap','error_class':type(exc).__name__})
                last_fault = type(exc).__name__
                state = {}
            if state.get('keeper_state') == 'verified' or is_locked(folder / '.clients'):
                activity = now
            if now - activity > IDLE_SECONDS:
                # Serialize idle shutdown with new action registration.
                with (folder.parent / '.startup').open('a') as gate:
                    fcntl.flock(gate, fcntl.LOCK_EX)
                    if not is_locked(folder / '.clients'):
                        append(folder, {'type':'observer_idle_exit'})
                        fcntl.flock(live_fd, fcntl.LOCK_UN)
                        return
                    activity = now
            time.sleep(1)


def run_action(prefix, action, cmd):
    folder, lease = ensure_monitor(prefix, lease=True)
    with lease:
        append(folder, {'type':'launch_requested', 'action':action})
        env = os.environ.copy()
        if action == 'uu':
            env.setdefault('WINEDEBUG', CHANNELS)
        counts = collections.Counter()
        last_flush = time.monotonic()
        write_failed = False
        def log_event(event):
            nonlocal write_failed
            try:
                append(folder, event)
            except OSError:
                # An unavailable disk must not close a live client's output pipe.
                if not write_failed:
                    print('Felix UU：诊断写入失败，会继续运行客户端。', file=sys.stderr)
                    write_failed = True

        def flush():
            for (encoded, second), n in counts.items():
                log_event({**json.loads(encoded), 'action':action, 'source':'launcher',
                                'observed_monotonic_s':second, 'count':n})
            counts.clear()
        try:
            proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        except OSError as exc:
            append(folder, {'type':'launch_exec_error', 'action':action, 'errno':exc.errno})
            raise
        with proc.stdout as output:
            while block := output.readline(8192):
                row = classify_line(block)
                now = time.monotonic()
                if row:
                    key = (json.dumps(row, sort_keys=True), int(now))
                    # First occurrence is visible while UU is still running; bursts are aggregated.
                    if key not in counts:
                        log_event({**row,'source':'launcher','action':action,'count':1})
                        counts[key] = 0
                    else:
                        counts[key] += 1
                if now - last_flush >= 2:
                    counts += collections.Counter()  # drop zero counts already written
                    flush()
                    last_flush = now
        counts += collections.Counter()
        flush()
        rc = proc.wait()
        log_event({'type':'launcher_exit','action':action,'exit_code':rc})
        return rc if rc >= 0 else 128-rc


def main():
    if len(sys.argv) == 6 and sys.argv[1] == '_monitor':
        return monitor(Path(sys.argv[2]), Path(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]))
    ap = argparse.ArgumentParser(description='Felix 测试版私有时间线')
    sub = ap.add_subparsers(dest='verb', required=True)
    for verb in ('exec', 'mark', 'latest', 'start'):
        p = sub.add_parser(verb)
        p.add_argument('--prefix', required=True, type=Path)
        if verb in ('exec','start'):
            p.add_argument('--action', required=True, choices=('uu','steam','setup'))
        if verb == 'exec':
            p.add_argument('command', nargs=argparse.REMAINDER)
        if verb == 'mark':
            p.add_argument('--event', choices=('launch-refused','issue'), required=True)
            p.add_argument('--reason', choices=('wrong-network','prepare','mixed-runner'))
    args = ap.parse_args()
    if args.verb == 'exec':
        command = args.command
        if command[:1] == ['--']:
            command = command[1:]
        if not command:
            ap.error('缺少启动命令')
        return run_action(args.prefix, args.action, command)
    if args.verb == 'latest':
        try:
            print(current(store_for(args.prefix)) / 'events.jsonl')
        except FileNotFoundError:
            print('尚无测试记录。',file=sys.stderr)
            return 1
    else:
        if args.verb == 'mark' and args.event == 'issue':
            # A report about the previous action still belongs to that run after idle shutdown.
            try:
                folder = current(store_for(args.prefix))
            except FileNotFoundError:
                print('当前没有测试记录可标记。',file=sys.stderr)
                return 1
        else:
            folder, _ = ensure_monitor(args.prefix)
        row = {'type':args.event} if args.verb == 'mark' else {'type':'launch_requested','action':args.action}
        if getattr(args,'reason',None):
            row['reason'] = args.reason
        append(folder,row)
        print(folder / 'events.jsonl')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, RuntimeError, ValueError) as error:
        print('Felix UU：本地记录器无法完成操作（' + type(error).__name__ + '）。', file=sys.stderr)
        sys.exit(1)
