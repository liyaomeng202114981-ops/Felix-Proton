# SPDX-License-Identifier: BSD-3-Clause
"""Read-only discovery of exact Steam Connection Manager TCP peers.

Source: Valve's unauthenticated HTTPS ISteamDirectory/GetCMListForConnect/v1
websockets response and timestamped Steam connection_log CM messages. No
request to the candidate servers is made. No account fields or log lines
are retained or returned. CMEndpoints.poll() is called by one owner thread.
"""
from __future__ import annotations

from itertools import islice
import ipaddress
import json
import os
from pathlib import Path
import queue
import re
import socket
import stat
import threading
import time
import urllib.request

DIRECTORY_HOST = 'api.steampowered.com'
URL = f'https://{DIRECTORY_HOST}/ISteamDirectory/GetCMListForConnect/v1/?cellid=0&cmtype=websockets&maxcount=40'
DIRECTORY_TTL = 20 * 60
HINT_TTL = 30 * 60
COMPLETED_TTL = 2 * 60 * 60
DNS_TTL = 180
LIVE_TTL = 120
READ_LIMIT = 128 * 1024
LINE_LIMIT = 2048
MAX_HINTS = 128
_HOST = re.compile(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.){1,3}steamserver\.net', re.ASCII)
_PREFIX = re.compile(rb'^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\]\s+(?:\[[^\]\r\n]{1,96}\]\s+){0,3}')
_PAIR = rb'([A-Za-z0-9.:-]{1,253}:\d{1,5}|\[[0-9A-Fa-f:]+\]:\d{1,5})'
_PING = re.compile(rb'^PingWebSocketCM\(\) \('+_PAIR+rb'\) starting(?:\.\.\.)?\s*$', re.I)
_CONNECT = re.compile(rb'^Connect\(\) starting connection \([A-Za-z0-9_ -]{1,40},\s*'+_PAIR+rb',\s*(WebSocket|TCP)\)', re.I)
_DONE = re.compile(rb'^ConnectionCompleted\(\) \('+_PAIR+rb',\s*(WebSocket|TCP)\)', re.I)


def public_ip(value, families):
    if not isinstance(value, str) or '%' in value:
        return None
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip.version not in families or not ip.is_global or ip.is_multicast or ip.is_reserved:
        return None
    return str(ip)


def _pair(value, families):
    if not isinstance(value, str) or len(value) > 265:
        return None
    host, sep, port = value.rpartition(':')
    if not sep or not port.isascii() or not port.isdecimal() or not 0 < int(port) < 65536:
        return None
    if host.startswith('[') and host.endswith(']'):
        host = host[1:-1]
        if ':' not in host:
            return None
    elif ':' in host:
        return None  # IPv6 endpoints require brackets
    addr = public_ip(host, families)
    if not addr:
        host = host.lower()
        if not _HOST.fullmatch(host):
            return None
    return (addr or host, int(port))


def directory_rows(payload: bytes, families=(4,)):
    if len(payload) > 128*1024:
        raise ValueError('directory_size')
    data = json.loads(payload)
    r = data.get('response') if isinstance(data, dict) else None
    if not isinstance(r,dict) or r.get('success') is not True or not isinstance(r.get('serverlist'),list):
        raise ValueError('directory_response')
    out = []
    for row in r['serverlist'][:80]:
        if not isinstance(row,dict) or row.get('type') != 'websockets' or row.get('realm') != 'steamglobal':
            continue
        endpoint = _pair(row.get('endpoint'), families)
        if endpoint and endpoint not in out:
            out.append(endpoint)
    if not out:
        raise ValueError('directory_no_eligible')
    return out


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _desktop_proxy():
    """Read the optional GNOME manual loopback proxy for this directory only."""
    try:
        from gi.repository import Gio
    except ImportError:
        return None

    schemas = Gio.SettingsSchemaSource.get_default()
    if schemas is None:
        return None
    schema = schemas.lookup('org.gnome.system.proxy', True)
    if schema is None:
        return None
    settings = Gio.Settings.new_full(schema, None, None)
    if settings.get_string('mode') != 'manual':
        return None
    ignored = settings.get_strv('ignore-hosts')
    if '*' in ignored:
        return None

    server = settings.get_child('https')
    if not server.get_string('host'):
        server = settings.get_child('http')
    host = server.get_string('host')
    port = server.get_int('port')
    try:
        address = ipaddress.ip_address('127.0.0.1' if host.lower() == 'localhost' else host)
    except ValueError:
        return None
    if not address.is_loopback or not 0 < port < 65536:
        return None
    authority = f'[{address}]' if address.version == 6 else str(address)
    proxy = f'http://{authority}:{port}'
    resolver = Gio.SimpleProxyResolver.new(proxy, ignored)
    if resolver.lookup(f'https://{DIRECTORY_HOST}:443/', None)[0] == proxy:
        return proxy
    return None


def _fetch(families):
    proxies = urllib.request.getproxies()
    proxy = None
    if not proxies.get('https') and not urllib.request.proxy_bypass(DIRECTORY_HOST):
        proxy = _desktop_proxy()
    if proxy:
        try:
            return _read_directory(families, {'https': proxy})
        except OSError:
            # A stopped local proxy must not prevent a working direct lookup.
            pass
    return _read_directory(families, proxies)


def _read_directory(families, proxies):
    req = urllib.request.Request(URL,headers={'Accept':'application/json','User-Agent':'Felix-Steam-CM/1.0'})
    handler = urllib.request.ProxyHandler(proxies)
    with urllib.request.build_opener(_NoRedirect(), handler).open(req,timeout=4) as res:
        if res.status != 200 or res.geturl() != URL or res.headers.get_content_type() != 'application/json':
            raise ValueError('directory_response')
        return directory_rows(res.read(128*1024+1),families)


def parse_cm_line(line, families=(4,)):
    """Return (kind, endpoint, log local wall seconds), without retaining IDs."""
    if len(line)>LINE_LIMIT or b'\0' in line:
        return None
    pfx = _PREFIX.match(line)
    if not pfx:
        return None
    body = line[pfx.end():]
    match = _PING.match(body) or _CONNECT.match(body)
    kind = 'candidate'
    if not match:
        match = _DONE.match(body)
        kind = 'completed'
    if not match:
        return None
    pair = _pair(match[1].decode('ascii'),families)
    if not pair:
        return None
    # A numeric completed peer only qualifies with a native Steam socket.
    # A local log's arbitrary numeric "candidate" does not authorize a rule.
    if (kind == 'completed') != bool(public_ip(pair[0],families)):
        return None
    try:
        stamped = time.mktime(time.strptime(pfx[1].decode('ascii'),'%Y-%m-%d %H:%M:%S'))
    except (ValueError,OverflowError,OSError):
        return None
    return kind, pair, stamped


def _resolve(host, families):
    af = socket.AF_INET if families == (4,) else socket.AF_INET6 if families == (6,) else socket.AF_UNSPEC
    return [row[4][0] for row in socket.getaddrinfo(host,None,af,socket.SOCK_STREAM,socket.IPPROTO_TCP)]


class CMEndpoints:
    """Bounded in-memory TTL caches. Background HTTPS and DNS never block poll()."""
    def __init__(self, connection_log:Path, *, families=(4,), max_entries=64):
        self.path = Path(connection_log)
        self.families = tuple(sorted(set(families)))
        if not self.families or any(n not in (4,6) for n in self.families) or not 1 <= max_entries <= 64:
            raise ValueError('invalid_families_or_limit')
        self.limit=max_entries
        self.hints, self.completed, self.live_cache = {}, {}, {}
        self.directory, self.dns, self.dns_retry = {}, {}, {}
        self.offset, self.identity, self.partial, self.discard = 0, None, b'', False
        self.next_fetch = self.next_read = 0
        self.results = queue.Queue()
        self.pending = set()
        self.closed = False
        self.directory_state = 'waiting'
        self.report = {'ready':False,'count':0,'directory':'waiting','live_confirmed':0}

    def _worker(self, key, fn, *args):
        self.pending.add(key)
        def run():
            try:
                value = fn(*args)
            except Exception:
                value = None  # Untrusted/server exception text can contain the request or hostname.
            self.results.put((key,value))
        threading.Thread(target=run,daemon=True,name='steam-cm-'+key[0]).start()

    def _receive(self, now):
        while True:
            try:
                key, value = self.results.get_nowait()
            except queue.Empty:
                break
            self.pending.discard(key)
            if key[0] == 'directory':
                self.next_fetch = now + (300 if value else 30)
                self.directory_state = 'ok' if value else 'unavailable'
                if value:
                    # Superseded entries retain only their original, bounded lifetime.
                    for p in value:
                        self.directory[p] = now+DIRECTORY_TTL
            else:
                host = key[1]
                addrs = list(dict.fromkeys(ip for v in (value or []) if (ip:=public_ip(v,self.families))))[:8]
                self.dns_retry[host] = now + (90 if addrs else 20)
                if addrs:
                    self.dns[host] = (now+DNS_TTL,addrs)

    def _read_log(self, mono, wall):
        try:
            fd = os.open(self.path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
            try:
                st = os.fstat(fd)
                if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid():
                    return
                identity=(st.st_dev,st.st_ino)
                if identity != self.identity or st.st_size < self.offset:
                    self.offset,self.identity,self.partial,self.discard=0,identity,b'',False
                if st.st_size-self.offset > READ_LIMIT:
                    self.offset=st.st_size-READ_LIMIT
                    self.partial=b''
                    self.discard=os.pread(fd,1,self.offset-1)!=b'\n'
                data=os.pread(fd,max(0,st.st_size-self.offset),self.offset)
                self.offset+=len(data)
            finally:
                os.close(fd)
        except OSError:
            return
        lines=(self.partial+data).split(b'\n')
        self.partial=lines.pop()
        if self.discard and lines:
            lines.pop(0)
            self.discard=False
        if len(self.partial)>LINE_LIMIT:
            self.discard=True
        if self.discard:
            self.partial=b''
        for line in lines:
            rec=parse_cm_line(line,self.families)
            if rec:
                kind,pair,stamp=rec
                ttl=HINT_TTL if kind=='candidate' else COMPLETED_TTL
                age=wall-stamp
                if -5 <= age < ttl:
                    store=self.hints if kind=='candidate' else self.completed
                    store[pair]=max(store.get(pair,0),mono + ttl-max(0,age))

    @staticmethod
    def _prune(cache,now,cap):
        for key in list(cache):
            if cache[key] <= now:
                del cache[key]
        if len(cache)>cap:
            for key in sorted(cache,key=cache.get)[:len(cache)-cap]:
                del cache[key]

    def poll(self, live_tcp=()):
        """Return {(public IP string, exact TCP port)}; sockets alone are insufficient."""
        if self.closed:
            return set()
        now = time.monotonic()
        self._receive(now)
        if now>=self.next_read:
            self._read_log(now,time.time())
            self.next_read=now+.2
        for cache in (self.hints,self.completed,self.directory,self.live_cache,self.dns_retry):
            self._prune(cache,now,MAX_HINTS)
        self.dns={h:v for h,v in self.dns.items() if v[0]>now}
        if now>=self.next_fetch and ('directory','') not in self.pending:
            self._worker(('directory',''),_fetch,self.families)
        # Recent log candidates take precedence over discovered but unused list entries.
        sources = list(dict.fromkeys([*sorted(self.hints,key=self.hints.get,reverse=True),
                                      *sorted(self.directory,key=self.directory.get,reverse=True)]))
        peers=[]
        dns_pending=sum(k[0]=='dns' for k in self.pending)
        for host, port in sources:
            addr=public_ip(host,self.families)
            if addr:
                peers.append((addr,port))
                continue
            if self.dns_retry.get(host,0)<=now and ('dns',host) not in self.pending and dns_pending<4:
                self._worker(('dns',host),_resolve,host,self.families)
                dns_pending+=1
            if host in self.dns:
                peers.extend((ip,port) for ip in self.dns[host][1])
        qualified=set(peers)|self.completed.keys()|self.live_cache.keys()
        active=set()
        for item in islice(live_tcp,512):
            if not isinstance(item,(list,tuple)) or len(item)!=2 or type(item[1]) is not int or not 0<item[1]<65536:
                continue
            ip=public_ip(item[0],self.families)
            p=(ip,item[1])
            if ip and p in qualified:
                active.add(p)
                self.live_cache[p]=now+LIVE_TTL
        selected=list(dict.fromkeys([*sorted(active),*sorted(self.live_cache,key=self.live_cache.get,reverse=True),*peers]))[:self.limit]
        self.report={'ready':bool(selected),'count':len(selected),'directory':self.directory_state,
                     'log_candidates':len(self.hints),'dns_hosts':len(self.dns),'live_confirmed':len(active)}
        return set(selected)

    def status(self):
        return dict(self.report)

    def close(self):
        # Outstanding bounded network requests are daemon workers; their results
        # are ignored. poll() never starts more requests after close.
        self.closed=True
        self.hints.clear()
        self.completed.clear()
        self.live_cache.clear()
        self.directory.clear()
        self.dns.clear()
        self.dns_retry.clear()
        self.report={'ready':False,'count':0,'directory':'closed','live_confirmed':0}
