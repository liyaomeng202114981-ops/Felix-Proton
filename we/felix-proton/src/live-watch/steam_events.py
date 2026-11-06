# SPDX-License-Identifier: BSD-3-Clause
"""Bounded incremental Steam CM/content event reader. Reads only native text logs."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import re
import stat

_FILES = {'connection': 'connection_log.txt', 'content': 'content_log.txt'}
_READ = 65536         # max new bytes per file per poll, apart from a small continuity check
_LINE = 8192
_LIMIT = 96           # matching lines per file per poll, with an explicit loss event
_STAMP = re.compile(rb'^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\]\s*')
_APP = re.compile(rb'^AppID\s+([1-9]\d{0,9})\b\s*', re.I)
_OK = re.compile(rb"\bRecvMsgClientLogOnResponse\(\)\s*:\s*(?:\[[^\]]{1,100}\]\s*)?['\"]OK['\"]", re.I)
_CM = re.compile(rb"\b(ConnectionDisconnected|StartAutoReconnect|ScheduleImmediateReconnect|ConnectFailed|Connect)\(", re.I)
_RETRY = re.compile(rb'\bin\s+(\d{1,5}(?:\.\d{1,3})?)\s*(?:sec(?:ond)?s?)\b', re.I)
_RATE = re.compile(rb'^Current download rate:\s*(\d{1,8}(?:\.\d{1,4})?)\s*(Kbps|Mbps|Gbps|KB/s|MB/s|GB/s)\b', re.I)
_FACTORS = {b'kbps': .001, b'mbps':1, b'gbps':1000, b'kb/s':.008, b'mb/s':8, b'gb/s':8000}
_ERRORS = (
    (b'no connection', 'no_connection'), (b'noconnection','no_connection'),
    (b'timeout','timeout'), (b'timed out','timeout'),
    (b'access denied','access_denied'), (b'disk write','disk_write'),
    (b'disk read','disk_read'), (b'corrupt','corrupt_content'),
    (b'content unavailable','content_unavailable'), (b'missing file','missing_files'),
    (b'canceled','canceled'), (b'cancelled','canceled'),
)
_CM_STATES = {'cm_logon_ok':'logged_on','cm_disconnected':'disconnected','cm_connecting':'connecting',
              'cm_connect_failed':'connect_failed','cm_auto_reconnect':'reconnect_pending'}


def _now():
    return datetime.now().astimezone().isoformat(timespec='milliseconds')


def _error(text, default='other'):
    return next((out for needle, out in _ERRORS if needle in text), default)


def _connection(body):
    if _OK.search(body):
        return {'type':'cm_logon_ok'}
    m = _CM.search(body)
    if m is None:
        return None
    name = m[1].lower()
    if name == b'connectiondisconnected':
        # Steam also logs "ConnectionDisconnected() not auto reconnecting ...".
        # It is not an additional disconnect transition.
        if re.match(rb'\)\s+not auto reconnecting', body[m.end():], re.I):
            return None
        return {'type':'cm_disconnected', 'error':_error(body.lower(), 'unspecified')}
    if name == b'connect':
        return {'type':'cm_connecting'}
    if name == b'connectfailed':
        return {'type':'cm_connect_failed','error':_error(body.lower())}
    event = {'type':'cm_auto_reconnect'}
    retry = _RETRY.search(body[m.end():])
    if retry and float(retry[1]) <= 86400:
        event['retry_seconds'] = float(retry[1])
    return event


def _content(body):
    app = _APP.match(body)
    if app:
        if int(app[1]) > 4294967295:
            return None
        body = body[app.end():]
    low = body.lower()
    rate = _RATE.match(body)
    if rate:
        event = {'type':'download_rate', 'rate_mbps':round(float(rate[1])*_FACTORS[rate[2].lower()], 6)}
    elif app and low.startswith(b'scheduler finished'):
        result = re.search(rb'\bresult\s+([^,)]{1,64})[,)]', low)
        if not result:
            event = {'type':'download_scheduler_finished','exitcode':'unknown'}
        elif result[1].strip() in (b'no error',b'ok',b'success'):
            event = {'type':'download_scheduler_finished','exitcode':'ok'}
        else:
            event = {'type':'download_scheduler_finished','exitcode':'error','error':_error(result[1])}
    elif app and low.startswith(b'scheduler update'):
        event = {'type':'download_schedule_updated'}
    elif app and (low.startswith(b'update started') or low.startswith(b'scheduler started')):
        event = {'type':'download_started'}
    elif app and re.match(rb'^update(?:\s+[a-z]+){0,3}\s+(?:canceled|cancelled|failed)\s*:', low):
        e = _error(low.partition(b':')[2])
        event = {'type':'download_update_error','error':e}
    elif re.match(rb'^failed to get (?:[^\r\n]{0,80}\s)?download sources?\b',low) or (
            b'::' in low and b'failed (' in low and
            any(x in low for x in (b'getserversforsteampipe', b'getsteamcontentservers'))):
        event = {'type':'download_source_failed','error':_error(low,'source_unavailable')}
    elif b'error: failed to get cdn auth' in low:
        event = {'type':'download_source_failed', 'error':'source_auth_failed'}
    elif b'no connection' in low or b'noconnection' in low:
        event = {'type':'content_no_connection','error':'no_connection'}
    else:
        return None
    if app:
        event['appid'] = int(app[1])
    return event


def classify(source: str, line: bytes):
    """Return only fixed event names and tightly typed numeric fields."""
    if len(line)>_LINE or b'\0' in line:
        return None
    m = _STAMP.match(line)
    if not m:
        return None
    body = line[m.end():]
    event = _connection(body) if source == 'connection' else _content(body) if source == 'content' else None
    if event:
        try:
            event['timestamp'] = datetime.fromisoformat(m[1].decode('ascii')).astimezone().isoformat(timespec='seconds')
        except (ValueError, OverflowError, OSError):
            return None
    return event


@dataclass
class _Cursor:
    identity: tuple[int, int] | None = None
    offset: int = 0
    stamp: int = 0
    anchor: bytes = b''
    pending: bytes = b''
    discard: bool = False
    readable: str = ''


class SteamEvents:
    def __init__(self, root: Path):
        self.root = Path(root)             # the directory containing the two .txt files
        self._cursor = {k:_Cursor() for k in _FILES}
        self._cm = None
        self._initial = self._round(baseline=True)

    def snapshot(self) -> dict:
        """One last observed CM state, with its own timestamp, or unknown."""
        return dict(self._cm) if self._cm else {'type':'cm_snapshot','state':'unknown','timestamp':None}

    def _remember(self, event):
        if event['type'] in _CM_STATES:
            self._cm = {'type':'cm_snapshot', 'state':_CM_STATES[event['type']], 'timestamp':event['timestamp']}

    def poll(self) -> list[dict]:
        first, self._initial = self._initial, []
        return first + self._round(baseline=False)

    @staticmethod
    def _meta(source, event, **fields):
        return {'timestamp':_now(), 'type':event, 'source':source, **fields}

    def _round(self, baseline):
        out = []
        for source, basename in _FILES.items():
            try:
                fd = os.open(self.root/basename, os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
                try:
                    st = os.fstat(fd)
                    if not stat.S_ISREG(st.st_mode):
                        raise OSError('not a regular log')
                    out.extend(self._read(fd,st,source,baseline))
                finally:
                    os.close(fd)
            except OSError as exc:
                state = 'missing' if isinstance(exc, FileNotFoundError) else 'unavailable'
                if self._cursor[source].readable != state:
                    out.append(self._meta(source,'steam_log_'+state))
                self._cursor[source] = _Cursor(readable=state)
                if source == 'connection':
                    self._cm = None
        return out

    def _read(self, fd, st, source, baseline):
        c = self._cursor[source]
        ident = (st.st_dev, st.st_ino)
        size = st.st_size
        change = None
        if baseline:
            change = 'baseline'
        elif c.readable == 'unavailable':
            change = 'resumed'
        elif not c.identity:
            change = 'appeared'
        elif ident != c.identity:
            change = 'rotated'
        elif size < c.offset:
            change = 'truncated'
        elif c.stamp != st.st_mtime_ns and c.anchor and (
                os.pread(fd,len(c.anchor),c.offset-len(c.anchor)) != c.anchor):
            change = 'rewritten'
        out = []
        if change:
            # An inaccessible log could have pre-existing records; avoid replay.
            previous = c.offset
            skip = change in ('baseline','resumed')
            c = self._cursor[source] = _Cursor(ident,size if skip else 0,readable='ok')
            out.append(self._meta(source,'steam_log_'+change, offset=c.offset, previous_offset=previous))
            if change in ('rotated','truncated','rewritten'):
                out.append(self._meta(source,'steam_log_gap', reason='previous_tail_unavailable'))
            if source == 'connection':
                self._cm = None
            if skip and size:
                c.discard = os.pread(fd,1,size-1) != b'\n'
                if source == 'connection':
                    # Only the latest recognizable transition from a 64 KiB tail;
                    # don't emit or retain earlier records.
                    start = max(0,size-_READ)
                    data = os.pread(fd,size-start,start)
                    complete = data.split(b'\n')[:-1]
                    if start:
                        complete = complete[1:]
                    for line in reversed(complete):
                        event = classify(source,line)
                        if event and event['type'] in _CM_STATES:
                            self._remember(event)
                            break
        if size > c.offset:
            start = c.offset
            if size-start > _READ:
                start = size-_READ
                out.append(self._meta(source,'steam_log_gap',dropped_bytes=start-c.offset, reason='byte_limit'))
                if source == 'connection':
                    self._cm = None
                c.pending = b''
                c.discard = os.pread(fd,1,start-1) != b'\n'
            block = os.pread(fd,size-start,start)
            c.offset = start+len(block)
            lines = (c.pending + block).split(b'\n')
            c.pending = lines.pop()
            if c.discard and lines:
                lines.pop(0)
                c.discard = False
            emitted = dropped = long_lines = 0
            for line in lines:
                if len(line)>_LINE:
                    long_lines += 1
                    continue
                event = classify(source,line)
                if event is not None:
                    self._remember(event)
                    if emitted < _LIMIT:
                        out.append(event)
                        emitted += 1
                    else:
                        dropped += 1
            if len(c.pending)>_LINE and not c.discard:
                long_lines += 1
                c.discard = True
            if c.discard:
                c.pending = b''
            if long_lines:
                out.append(self._meta(source,'steam_log_gap', dropped_lines=long_lines, reason='long_line'))
            if dropped:
                out.append(self._meta(source,'steam_log_gap', dropped_events=dropped, reason='event_limit'))
        if change or c.stamp != st.st_mtime_ns or size != c.offset:
            n = min(c.offset,48)
            c.anchor = os.pread(fd,n,c.offset-n)
        c.stamp = st.st_mtime_ns
        return out
