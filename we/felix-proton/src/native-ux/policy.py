# SPDX-License-Identifier: BSD-3-Clause
"""IPv4 TCP endpoint exceptions in a validated private UU network namespace."""
import contextlib
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import stat
import struct
import subprocess
import tempfile


class PolicyError(Exception):
    """Privacy-preserving fixed reason. Never includes endpoints or shell commands."""


PROTOCOL = 196
METRIC = 42420
MAX_ENDPOINTS = 64
TABLES = range(41200, 41328)
PREFERENCES = range(14300, 14428)


def _key(addr, port):
    try:
        ip = ipaddress.ip_address(addr)
    except (ValueError, TypeError):
        raise PolicyError("invalid_endpoint") from None
    if ip.version != 4:
        raise PolicyError("unsupported_family")
    if (not isinstance(addr, str) or not isinstance(port, int) or isinstance(port, bool)
            or not 1 <= port <= 65535 or ip.is_loopback or ip.is_multicast or ip.is_unspecified
            or ip.is_link_local or ip.is_reserved):
        raise PolicyError("invalid_endpoint")
    return str(ip), port


def _endpoints(values):
    result = set()
    try:
        for i, value in enumerate(values):
            if i >= MAX_ENDPOINTS:
                raise PolicyError("endpoint_limit")
            result.add(_key(*value))
    except (TypeError, ValueError):
        raise PolicyError("invalid_endpoint") from None
    return result


def _private(info):
    return info.st_uid == os.getuid() and not (info.st_mode & 0o077)


class Policy:
    """FDs must refer to a verified keeper. Public methods return counts only.

    The private ledger is per namespace. It records permitted kernel objects
    before adding them so cleanup is possible after interruption. A missing
    ledger never authorizes adoption or removal of existing objects.
    """
    def __init__(self, userns_fd, netns_fd, state_file):
        self.input_fds = userns_fd, netns_fd
        self.file = Path(state_file)
        self.handles = None

    def __enter__(self):
        stack = contextlib.ExitStack()
        try:
            u = os.dup(self.input_fds[0]); stack.callback(os.close,u)
            n = os.dup(self.input_fds[1]); stack.callback(os.close,n)
            ns = [os.readlink(f"/proc/self/fd/{i}") for i in (u,n)]
            if (os.geteuid() == 0 or not ns[0].startswith("user:[") or not ns[1].startswith("net:[")
                    or ns[0] == os.readlink("/proc/self/ns/user") or ns[1] == os.readlink("/proc/self/ns/net")):
                raise PolicyError("unsafe_namespace")
            owner = fcntl.ioctl(n,0xb701)  # NS_GET_USERNS on the network namespace
            try:
                if os.readlink(f"/proc/self/fd/{owner}") != ns[0]:
                    raise PolicyError("namespace_owner_mismatch")
            finally:
                os.close(owner)
            uid = struct.unpack("=I", fcntl.ioctl(u,0xb704,b"\0"*4))[0]  # NS_GET_OWNER_UID
            if uid != os.getuid():
                raise PolicyError("namespace_owner_mismatch")
            self.identity = [Path("/proc/sys/kernel/random/boot_id").read_text().strip(),*ns]
            self.handles = (u,n)
        except (OSError,ValueError):
            stack.close()
            raise PolicyError("namespace_unavailable") from None
        except BaseException:
            stack.close()
            raise
        self.stack = stack
        return self

    def __exit__(self,*exc):
        self.stack.close()
        self.handles = None

    def _ip(self,*args, read=False):
        if self.handles is None:
            raise PolicyError("namespace_not_open")
        u,n = self.handles
        cmd = ["/usr/bin/nsenter","--preserve-credentials", f"--user=/proc/self/fd/{u}",
               f"--net=/proc/self/fd/{n}", "--","/usr/sbin/ip"]
        if read:
            cmd += ["-N","-j","-details"]
        try:
            p = subprocess.run([*cmd,*map(str,args)],pass_fds=(u,n),stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=3,env={"LC_ALL":"C","PATH":"/usr/bin:/usr/sbin"})
            if p.returncode or len(p.stdout)>8*1024*1024:
                raise PolicyError("netlink_query_failed" if read else "netlink_change_failed")
            if read:
                rows = json.loads(p.stdout)
                if not isinstance(rows,list):
                    raise PolicyError("invalid_netlink_reply")
                return rows
        except (OSError,ValueError,subprocess.SubprocessError):
            raise PolicyError("netlink_query_failed" if read else "netlink_change_failed") from None

    @contextlib.contextmanager
    def _lock(self):
        if self.handles is None:
            raise PolicyError("namespace_not_open")
        folder = self.file.parent
        folder.mkdir(mode=0o700,parents=True,exist_ok=True)
        try:
            fd = os.open(folder,os.O_DIRECTORY|os.O_RDONLY|os.O_NOFOLLOW)
            try:
                if not _private(os.fstat(fd)):
                    raise PolicyError("state_directory_not_private")
                fcntl.flock(fd,fcntl.LOCK_EX)
                yield
            finally:
                os.close(fd)
        except OSError:
            raise PolicyError("state_io_failed") from None

    def _load(self):
        try:
            fd=os.open(self.file,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW)
        except FileNotFoundError:
            return None
        except OSError:
            raise PolicyError("invalid_state") from None
        try:
            st=os.fstat(fd)
            if not _private(st) or not stat.S_ISREG(st.st_mode) or st.st_size>64*1024:
                raise PolicyError("invalid_state")
            data=json.loads(os.read(fd,65537))
            if data["version"]!=1 or data["namespace"]!=self.identity:
                raise PolicyError("state_namespace_mismatch")
            if data["table"] not in TABLES or data["pref"] not in PREFERENCES:
                raise PolicyError("invalid_state")
            b=data["baseline"]
            if not b["dev"] or b["dev"] in ("lo","UU") or b["ifindex"]<=0:
                raise PolicyError("invalid_state")
            for field in ("gateway","source"):
                ipaddress.IPv4Address(b[field])
            _endpoints(data["settled"])
            # WAL can contain old and new disjoint desired sets.
            if len(data["owned"]) > 2*MAX_ENDPOINTS:
                raise PolicyError("invalid_state")
            for entry in data["owned"]:
                _key(*entry)
            return data
        except (OSError,TypeError,ValueError,KeyError):
            raise PolicyError("invalid_state") from None
        finally:
            os.close(fd)

    def _save(self,state):
        path=None
        try:
            with tempfile.NamedTemporaryFile(mode="w",encoding="utf-8",dir=self.file.parent,
                                             prefix=".cm-ledger-",delete=False) as f:
                path=Path(f.name)
                json.dump(state,f,sort_keys=True); f.write("\n")
                f.flush(); os.fsync(f.fileno())
            os.replace(path,self.file)
            dfd=os.open(self.file.parent,os.O_DIRECTORY|os.O_RDONLY)
            try: os.fsync(dfd)
            finally: os.close(dfd)
        finally:
            if path: path.unlink(missing_ok=True)

    def _tables(self):
        return (self._ip("-4","rule","show",read=True),
                self._ip("-4","route","show","table","all",read=True))

    def _baseline(self,uplink):
        links=self._ip("link","show",read=True)
        if any(r["ifname"]=="UU" for r in links):
            raise PolicyError("tunnel_active")
        rows=self._ip("-4","route","show","table","main","default",read=True)
        if len(rows)!=1:
            raise PolicyError("ambiguous_default_route")
        row=rows[0]; dev=row.get("dev")
        link=next((r for r in links if r["ifname"]==dev),None)
        if (not link or dev in ("lo","UU") or uplink is not None and dev!=uplink
                or "UP" not in link["flags"] or not row.get("gateway") or row.get("nexthops")
                or row.get("type","1")!="1"):
            raise PolicyError("unverified_uplink")
        addr=self._ip("-4","addr","show","dev",dev,read=True)
        candidates={a["local"] for r in addr for a in r.get("addr_info",[]) if a["family"]=="inet"
                    and a["scope"] in ("global","0") and not (a.get("tentative") or a.get("dadfailed"))}
        # -N can vary the scope representation across iproute2 versions.
        src=row.get("prefsrc") or (next(iter(candidates)) if len(candidates)==1 else None)
        if not src or src not in candidates:
            raise PolicyError("ambiguous_uplink_source")
        return {"dev":dev,"ifindex":link["ifindex"],"source":src,"gateway":row["gateway"]}

    def _verify_anchor(self,b):
        rows=self._ip("-4","addr","show","dev",b["dev"],read=True)
        if not any(r["ifindex"]==b["ifindex"] and "UP" in r["flags"] and
                   any(a.get("local")==b["source"] for a in r.get("addr_info",[])) for r in rows):
            raise PolicyError("uplink_changed")
        defaults = self._ip("-4","route","show","table","main","default",read=True)
        if not any(r.get("dev")==b["dev"] and r.get("gateway")==b["gateway"] for r in defaults):
            raise PolicyError("uplink_default_changed")

    @staticmethod
    def _report(state,changed):
        keys={tuple(x) for x in state["settled"]} if state else set()
        return {"baseline_families":[4] if state else [],"rules":len(keys),
                "routes":len({x[0] for x in keys}),"changed":changed}

    def capture_baseline(self,uplink=None):
        with self._lock():
            state=self._load()
            b=self._baseline(uplink)
            if state:
                if state["baseline"]!=b:
                    raise PolicyError("baseline_changed")
                self._inspect(state)
                return self._report(state,False)
            rules,routes=self._tables()
            other_rules=self._ip("-6","rule","show",read=True)
            other_routes=self._ip("-6","route","show","table","all",read=True)
            used_tables={str(r.get("table","254")) for r in rules+routes+other_rules+other_routes}
            table=next((i for i in TABLES if str(i) not in used_tables),None)
            priorities={r["priority"] for r in rules+other_rules}
            main=[r["priority"] for r in rules if str(r.get("table"))=="254"]
            if not main or not any(r.get("priority")==0 and str(r.get("table"))=="255" for r in rules):
                raise PolicyError("nonstandard_policy")
            pref=next((i for i in PREFERENCES if i not in priorities and i<min(main)),None)
            if table is None or pref is None:
                raise PolicyError("no_free_policy_slot")
            state={"version":1,"namespace":self.identity,"baseline":b,"pref":pref,"table":table,"owned":[],"settled":[]}
            self._save(state)
            return self._report(state,True)

    def _inspect(self,s):
        rules,routes=self._tables()
        table=str(s["table"]); pref=s["pref"]; b=s["baseline"]
        owned={tuple(e) for e in s["owned"]}; ips={ip for ip,_ in owned}
        rr=set(); rt=set()
        for r in rules:
            if str(r.get("table"))!=table and r.get("priority")!=pref: continue
            addr=r.get("dst","").removesuffix("/32"); key=(addr,r.get("dport"))
            if (set(r)-{"priority","src","dst","ipproto","dport","dport_mask","table","protocol"}
                    or r.get("src")!="all" or r.get("ipproto") not in ("ipproto-6","tcp","6")
                    or r.get("dport_mask","0xffff")!="0xffff" or str(r.get("protocol"))!=str(PROTOCOL)
                    or r.get("priority")!=pref or str(r.get("table"))!=table or key not in owned or key in rr):
                raise PolicyError("foreign_rule_conflict")
            rr.add(key)
        for r in routes:
            if str(r.get("table","254"))!=table: continue
            addr=r.get("dst","").removesuffix("/32")
            if (set(r)-{"type","dst","gateway","dev","table","protocol","scope","prefsrc","metric","flags"}
                    or str(r.get("type","1"))!="1" or str(r.get("scope","0"))!="0" or r.get("flags")!=["onlink"]
                    or str(r.get("protocol"))!=str(PROTOCOL) or r.get("metric")!=METRIC
                    or (r.get("dev"),r.get("gateway"),r.get("prefsrc"))!=(b["dev"],b["gateway"],b["source"])
                    or addr not in ips or addr in rt):
                raise PolicyError("foreign_route_conflict")
            rt.add(addr)
        return rr,rt

    def _apply(self,s,wanted,actual):
        rules,routes=actual
        ips={ip for ip,_ in wanted}
        b=s["baseline"]
        def route(action,addr):
            self._ip("-4","route",action,"table",s["table"],addr+"/32","via",b["gateway"],"dev",b["dev"],
                     "onlink","src",b["source"],"proto",PROTOCOL,"metric",METRIC)
        def rule(action,item):
            ip,port=item
            self._ip("-4","rule",action,"pref",s["pref"],"to",ip+"/32","ipproto","tcp","dport",port,
                     "lookup",s["table"],"protocol",PROTOCOL)
        for ip in sorted(ips-routes): route("add",ip)
        for key in sorted(wanted-rules): rule("add",key)
        for key in sorted(rules-wanted): rule("del",key)
        for ip in sorted(routes-ips): route("del",ip)

    def _reconcile(self,s,wanted):
        # A pre-existing unowned row never authorizes an addition or a delete.
        actual=self._inspect(s)
        old={tuple(e) for e in s["settled"]}
        if wanted:
            self._verify_anchor(s["baseline"])
        target=(wanted,{ip for ip,_ in wanted})
        if actual==target and old==wanted and set(map(tuple,s["owned"]))==wanted:
            return self._report(s,False)
        allowed=set(map(tuple,s["owned"]))
        if allowed!=old and wanted:
            # Finish recovery before accepting another disjoint request. WAL
            # stays bounded and a failed transaction cannot acquire new rows.
            self._apply(s,old,actual)
            actual=self._inspect(s)
            if actual!=(old,{ip for ip,_ in old}):
                raise PolicyError("recovery_pending")
            s["owned"]=sorted(old)
            self._save(s)
        s["owned"]=sorted(set(map(tuple,s["owned"]))|wanted)
        self._save(s)
        try:
            self._apply(s,wanted,actual)
            if self._inspect(s)!=target:
                raise PolicyError("policy_verification_failed")
            # A higher-priority VPN rule could have superseded the exception.
            for addr,port in sorted(wanted-actual[0]):
                r=self._ip("-4","route","get",addr,"ipproto","tcp","dport",port,read=True)
                if len(r)!=1 or str(r[0].get("table"))!=str(s["table"]) or r[0].get("dev")!=s["baseline"]["dev"]:
                    raise PolicyError("earlier_rule_overrides")
        except PolicyError as original:
            try:
                self._apply(s,old,self._inspect(s))
                if self._inspect(s)!=(old,{ip for ip,_ in old}):
                    raise PolicyError("recovery_pending")
                s["owned"]=s["settled"]
                self._save(s)
            except PolicyError:
                raise PolicyError("recovery_pending") from None
            raise original from None
        s["owned"]=s["settled"]=sorted(wanted)
        self._save(s)
        return self._report(s,True)

    def reconcile(self,endpoints):
        wanted=_endpoints(endpoints)
        with self._lock():
            s=self._load()
            if not s:
                raise PolicyError("baseline_required")
            return self._reconcile(s,wanted)

    def rollback(self):
        with self._lock():
            s=self._load()
            if not s:
                return self._report(None,False)
            self._reconcile(s,set())
            self.file.unlink()
            return self._report(None,True)
