# SPDX-License-Identifier: BSD-3-Clause
"""Passive metadata-only game route observations. Poll every 5–10 seconds."""
import collections
import contextlib
import hashlib
import ipaddress
import os
from pathlib import Path
import re
import select
import subprocess
import time

import net_beta


ROW = re.compile(rb"^\[([0-9-]+ [0-9:]+)\] AppID (\d{1,10}) (adding PID|no longer tracking PID) (\d{1,10})\b")
LOG_LIMIT = 512 * 1024
MAX_PIDS = 192
MAX_FDS = 2048
MAX_FLOWS = 8
PROC = Path("/proc")
# Linux or Wine main images for this test. Other native apps can match their
# installation directory name. Never inspect arbitrary Steam child FDs.
KNOWN = {730: {"cs2", "cs2.exe"}, 570: {"dota2", "dota2.exe"},
         1808500: {"pioneergame.exe", "arcraiders.exe"}}
HELPER = re.compile(r"anti.?cheat|battleye|bedaisy|beservice|easyanticheat|crash|helper|launcher|bootstrap|redist|overlay|protected|start_protected|guard|antitamper", re.I)
WINE = re.compile(r"wine(?:64)?(?:-preloader)?$")
SOCKET = re.compile(r"socket:\[([0-9]+)\]")


def _clean_name(value):
    return re.sub(r"[^a-z0-9]", "", value.lower().removesuffix(".exe"))


def _wine_image_arg(p, candidates):
    # UE renames its process leader to GameThread. Read only the executable
    # token(s), unbuffered and NUL-bounded, never shell text or launch options.
    def basename(stream):
        buf = bytearray()
        while len(buf) <= 1024:
            c = stream.read(1)
            if c == b"\0":
                return bytes(buf).replace(b"\\", b"/").rsplit(b"/",1)[-1].decode("ascii","replace").lower()
            if not c:
                break
            buf.extend(c)
        return ""
    with (p/"cmdline").open("rb", buffering=0) as stream:
        first = basename(stream)
        return (basename(stream) if WINE.fullmatch(first) else first) in candidates


def _main_image(appid, p):
    # Require a known main image before examining its socket descriptors.
    comm = (p/"comm").read_bytes().strip().decode("ascii", "replace").lower()
    image = Path(os.readlink(p/"exe").removesuffix(" (deleted)"))
    name = image.name.lower()
    if HELPER.search(name) or HELPER.search(comm):
        return False
    if WINE.fullmatch(name):
        candidates = KNOWN.get(appid, ())
        if comm in candidates:
            return True
        return bool(candidates) and comm == "gamethread" and _wine_image_arg(p, candidates)
    if name in KNOWN.get(appid, ()) and "steamapps" in image.parts and "common" in image.parts:
        return True
    # A native program tracked by Steam can also be identified when its
    # binary has the exact same name as its installation directory.
    parts = image.parts
    for i in range(1, len(parts)-2):
        if parts[i-1:i+1] != ("steamapps", "common"):
            continue
        return bool(_clean_name(name)) and _clean_name(name) == _clean_name(parts[i+1])
    return False


def _start(p):
    return int((p/"stat").read_bytes().rsplit(b") ", 1)[1].split()[19])


def _fd_inodes(p, deadline):
    result = set()
    with os.scandir(p/"fd") as entries:
        for i, e in enumerate(entries):
            if i >= MAX_FDS or i % 64 == 0 and time.monotonic() >= deadline:
                return result, True
            try:
                m = SOCKET.fullmatch(os.readlink(e.path))
            except (FileNotFoundError, ProcessLookupError):
                continue
            if m:
                result.add(int(m[1]))
    return result, False


def _endpoint(value):
    host, port = value.rsplit(":", 1)
    host = host.strip("[]")
    if "%" in host or not port.isdecimal():
        raise ValueError()
    ip = ipaddress.ip_address(host)
    if getattr(ip, "ipv4_mapped", None) is not None:
        ip = ip.ipv4_mapped
    return str(ip), int(port)


def _sockets(raw, owned):
    for line in raw.splitlines():
        ino = re.search(rb"\bino:(\d+)\b", line)
        if not ino or int(ino[1]) not in owned:
            continue
        inode = int(ino[1])
        fields = line.split(maxsplit=6)
        if len(fields)<6 or fields[0] not in (b"tcp", b"udp"):
            continue
        if fields[0] == b"udp":
            yield inode, None, "udp_no_peer" if fields[1] == b"UNCONN" else "udp_no_byte_history"
            continue
        if fields[1] != b"ESTAB":
            continue
        try:
            src, sport = _endpoint(fields[4].decode("ascii"))
            dst, dport = _endpoint(fields[5].decode("ascii"))
            peer = ipaddress.ip_address(dst)
            if peer.is_loopback or peer.is_unspecified or peer.is_multicast or peer.is_link_local:
                continue
        except (ValueError, UnicodeError):
            yield inode, None, "endpoint_unavailable"
            continue
        if re.search(rb"\bfwmark:(?!0+(?:\s|$)|0x0+(?:\s|$))", line):
            yield inode, None, "socket_policy_unconfirmed"
            continue
        counters = dict(re.findall(rb"\b(bytes_acked|bytes_received):(\d+)\b", line))
        if not counters:
            yield inode, None, "tcp_counters_unavailable"
            continue
        # Include both the endpoint tuple and socket cookie to guard inode reuse.
        sk = re.search(rb"\bsk:([0-9a-fA-F]+)\b",line)
        flow = (peer.version, src, sport, dst, dport, sk[1] if sk else b"")
        yield inode, (flow, int(counters.get(b"bytes_acked", 0)), int(counters.get(b"bytes_received", 0))), None


@contextlib.contextmanager
def _namespace(prefix):
    uid = os.getuid()
    rt = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/shorin-proton-wrapper-{uid}")
    key = hashlib.sha256(os.fsencode(prefix.resolve())).hexdigest()[:16]
    session = rt/"shorin-proton-wrapper/sessions"/key
    ident = net_beta._keeper(PROC, session, uid)
    p, _, ns = ident
    with contextlib.ExitStack() as stack:
        handles = []
        for kind in ("user","net"):
            fd = os.open(p/"ns"/kind, os.O_RDONLY)
            stack.callback(os.close, fd)
            if os.readlink(f"/proc/self/fd/{fd}") != os.readlink(p/"ns"/kind):
                raise ValueError()
            handles.append(fd)
        if ident != net_beta._keeper(PROC, session, uid):
            raise ValueError()
        yield ns, tuple(handles)


def _read_cmd(handles, args, deadline, limit=1024*1024):
    import json
    user, network = handles
    cmd = ["/usr/bin/nsenter", "--preserve-credentials", f"--user=/proc/self/fd/{user}",
           f"--net=/proc/self/fd/{network}", "--", *args]
    if time.monotonic() >= deadline:
        raise TimeoutError()
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          stdin=subprocess.DEVNULL, pass_fds=handles, env=dict(os.environ, LC_ALL="C")) as child:
        data = bytearray()
        try:
            while len(data) <= limit:
                seconds = deadline-time.monotonic()
                if seconds <= 0 or not select.select([child.stdout], [], [], seconds)[0]:
                    raise TimeoutError()
                chunk = os.read(child.stdout.fileno(), min(65536,limit+1-len(data)))
                if not chunk:
                    if child.wait(timeout=max(.01, deadline-time.monotonic())):
                        raise ValueError()
                    return bytes(data) if args[0].endswith("/ss") else json.loads(data)
                data.extend(chunk)
            raise ValueError()
        finally:
            if child.poll() is None:
                child.kill()


def _route(flow, handles, deadline, defaults):
    family, src, sp, dst, dp, _ = flow
    args = ["/usr/sbin/ip","-j",f"-{family}","route"]
    rows = _read_cmd(handles,[*args,"get",dst,"from",src,"ipproto","tcp","sport",str(sp),"dport",str(dp)],
                     deadline,8192)
    if len(rows) != 1:
        return "unknown"
    dev = rows[0].get("dev")
    if dev == "UU":
        return "uu"
    if family not in defaults:
        defaults[family] = {r.get("dev") for r in _read_cmd(handles,[*args,"show","default"],deadline,32768)}
    return "direct" if dev and dev != "lo" and dev in defaults[family] else "unknown"


def _game(appid):
    return {"appid":appid, "uu":0, "direct":0, "unknown":0, "uu_acked_bytes":0, "uu_received_bytes":0,
            "direct_acked_bytes":0, "direct_received_bytes":0, "observed_uu":0, "observed_direct":0,
            "unknown_reasons":set()}


def _unknown(row, why):
    row["unknown"] += 1
    row["unknown_reasons"].add(why)


class GameRoutes:
    """All endpoint and PID associations are transient. Returned rows contain only counts."""
    def __init__(self, prefix:Path, steam_logs:Path):
        self.prefix = Path(prefix)
        p = Path(steam_logs)
        self.log = p if p.name == "gameprocess_log.txt" else p/"gameprocess_log.txt"
        self.file = self.offset = None
        self.partial = b""
        self.tracked = {}
        self.previous = {}
        self.hz = os.sysconf("SC_CLK_TCK")
        self.boot = next(int(l.split()[1]) for l in (PROC/"stat").read_bytes().splitlines() if l.startswith(b"btime "))

    def _tail(self):
        with self.log.open("rb") as f:
            stat = os.fstat(f.fileno())
            ident = (stat.st_dev, stat.st_ino)
            if ident != self.file or stat.st_size < self.offset or stat.st_size-self.offset > LOG_LIMIT:
                self.file, self.offset, self.partial = ident, max(0, stat.st_size-LOG_LIMIT), b""
                self.tracked.clear()
                self.previous.clear()
                f.seek(self.offset)
                if self.offset:
                    f.readline(LOG_LIMIT)
            else:
                f.seek(self.offset)
            data = self.partial + f.read(LOG_LIMIT)
            self.offset = f.tell()
        lines = data.split(b"\n")
        self.partial = lines.pop()[-256:]
        for line in lines:
            m = ROW.match(line)
            if not m: continue
            appid, pid = int(m[2]), int(m[4])
            if m[3] == b"adding PID":
                # Log timestamps have whole-second resolution. Refuse a PID
                # whose current process started after that add event.
                try:
                    added = time.mktime(time.strptime(m[1].decode("ascii"),"%Y-%m-%d %H:%M:%S"))
                    p = PROC/str(pid)
                    if p.stat().st_uid != os.getuid(): continue
                    tick = _start(p)
                    if self.boot + tick/self.hz >= added+2: continue
                    self.tracked[(appid,pid)] = tick
                    if len(self.tracked) > MAX_PIDS:
                        self.tracked.pop(next(iter(self.tracked)))
                except (OSError,ValueError,IndexError,OverflowError): continue
            else:
                self.tracked.pop((appid,pid),None)

    def _owned(self, ns, result, deadline):
        owners = collections.defaultdict(set)
        recognized = set()
        for (appid,pid), tick in list(self.tracked.items()):
            p = PROC/str(pid)
            try:
                if time.monotonic() >= deadline:
                    _unknown(result.setdefault(appid,_game(appid)), "scan_time_limit")
                    continue
                if p.stat().st_uid != os.getuid() or _start(p) != tick:
                    self.tracked.pop((appid,pid),None)
                    continue
                row = result.setdefault(appid, _game(appid))
                if os.readlink(p/"ns/net") != ns:
                    _unknown(row,"different_namespace")
                    continue
                if not _main_image(appid, p):
                    continue
                recognized.add(appid)
                inos, truncated = _fd_inodes(p, deadline)
                if _start(p) != tick or os.readlink(p/"ns/net") != ns:
                    _unknown(row,"process_changed")
                    continue
                if truncated:
                    _unknown(row,"fd_scan_limited")
                for ino in inos:
                    owners[ino].add(appid)
            except (FileNotFoundError, ProcessLookupError):
                self.tracked.pop((appid,pid),None)
            except (PermissionError, ValueError, OSError, IndexError):
                _unknown(result.setdefault(appid, _game(appid)),"process_unavailable")
        for appid,row in result.items():
            if appid not in recognized and not row["unknown"]:
                _unknown(row,"main_image_unconfirmed")
        return owners

    def _sample(self, ns, handles, result):
        deadline = time.monotonic()+1.5
        owners = self._owned(ns, result, deadline)
        if not owners:
            self.previous.clear()
            return
        raw = _read_cmd(handles,["/usr/bin/ss","-H","-n","-t","-u","-e","-i","-O","-a"],deadline)
        eligible=[]
        for inode, item, reason in _sockets(raw, owners):
            apps=owners[inode]
            if len(apps)!=1 or reason:
                for a in apps: _unknown(result[a], reason or "shared_socket")
                continue
            eligible.append((next(iter(apps)),inode,item))
        eligible.sort(key=lambda e:(e[0],e[1]))
        # Keep measuring the same small set long enough to establish deltas.
        # Rotate only when flows vanish; report any uncaptured remainder.
        selected=sorted(eligible,key=lambda e:(ns,e[0],e[1],e[2][0]) not in self.previous)
        samples, defaults = {}, {}
        for i,(appid,inode,(flow,ack,recv)) in enumerate(selected):
            row = result[appid]
            if i >= MAX_FLOWS:
                _unknown(row,"flow_limit")
                continue
            try:
                route = _route(flow,handles,deadline,defaults)
            except (OSError, ValueError,KeyError,TypeError,subprocess.SubprocessError):
                route = "unknown"
            if route in ("uu","direct"):
                row["observed_"+route] += 1
            key = (ns,appid,inode,flow)
            old = self.previous.get(key)
            samples[key] = route,ack,recv
            if not old:
                _unknown(row,"first_sample")
            elif route=="unknown" or route!=old[0] or ack<old[1] or recv<old[2]:
                _unknown(row,"route_or_counter_changed")
            elif ack>old[1] or recv>old[2]:
                row[route]+=1
                row[route+"_acked_bytes"]+=ack-old[1]
                row[route+"_received_bytes"]+=recv-old[2]
        self.previous=samples

    def poll(self)->dict:
        result={}
        try:
            self._tail()
            if self.tracked:
                with _namespace(self.prefix) as (ns,handles):
                    self._sample(ns,handles,result)
            else:
                self.previous.clear()
        except (OSError, ValueError, IndexError, RuntimeError, subprocess.SubprocessError):
            self.previous.clear()
            for appid,_ in self.tracked:
                if appid not in result: result[appid]=_game(appid)
                if "sample_unavailable" not in result[appid]["unknown_reasons"]:
                    _unknown(result[appid],"sample_unavailable")
        for row in result.values():
            row["unknown_reasons"]=sorted(row["unknown_reasons"])
        return {"games":[result[k] for k in sorted(result)]}
