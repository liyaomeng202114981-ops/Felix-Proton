"""Read network observations from an existing shorin-proton-wrapper session."""
import hashlib
import os
from pathlib import Path
import re
import stat


def _unknown(keeper="unverified"):
    return {"keeper_state": keeper, "uu_device": "unknown", "uu_ipv4_routes": None,
            "uu_rx_bytes": None, "uu_tx_bytes": None, "steam_network": "unknown"}


def _marker(path, uid):
    # A stale socket, FIFO, or symlink must not block the background sampler.
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != uid:
            raise ValueError("invalid marker")
        data = os.read(fd, 128)
        if len(data) >= 128:
            raise ValueError("oversize marker")
        return data.strip().decode("ascii")
    finally:
        os.close(fd)


def _keeper(proc, session, uid):
    pid = _marker(session / "keeper.pid", uid)
    if not re.fullmatch(r"[1-9][0-9]{0,9}", pid):
        raise ValueError("invalid PID")
    p = proc / pid
    netns = _marker(session / "netns", uid)
    userns = _marker(session / "userns", uid)
    if (p.stat().st_uid != uid or not re.fullmatch(r"net:\[[0-9]+\]", netns)
            or not re.fullmatch(r"user:\[[0-9]+\]", userns)
            or os.readlink(p / "ns/net") != netns or os.readlink(p / "ns/user") != userns
            or os.readlink(proc / "self/ns/net") == netns):
        raise ValueError("keeper namespace or owner mismatch")
    # In the tested wrapper the shell execs: python3 - "$session".
    with (p / "cmdline").open("rb") as f:
        args = f.read(16385).split(b"\0")
    if (len(args) != 4 or os.path.basename(args[0]) != b"python3" or args[1] != b"-"
            or args[2] != os.fsencode(session) or args[3]):
        raise ValueError("keeper command mismatch")
    with (p / "stat").open("rb") as f:
        start = int(f.read(2048).rsplit(b") ", 1)[1].split()[19])
    return p, start, netns


def _device(p):
    with (p / "net/dev").open("rb") as f:
        header = f.readline()
        if b"Receive" not in header or b"Transmit" not in header or b"bytes" not in f.readline():
            raise ValueError("unreadable device table")
        seen = False
        for line in f:
            name, separator, values = line.rpartition(b":")
            if not separator:
                raise ValueError("invalid device record")
            seen = True
            if name.strip() == b"UU":
                cells = values.split()
                if len(cells) != 16 or not all(v.isdigit() for v in cells):
                    raise ValueError("invalid counters")
                return "present", int(cells[0]), int(cells[8])
        if not seen:
            raise ValueError("empty device table")
        return "absent", None, None


def _routes(p):
    with (p / "net/route").open("rb") as f:
        if f.readline().split()[:3] != [b"Iface", b"Destination", b"Gateway"]:
            raise ValueError("unreadable IPv4 route table")
        count = 0
        for line in f:
            fields = line.split()
            if len(fields) < 8:
                raise ValueError("invalid IPv4 route record")
            count += fields[0] == b"UU"
        return count


def _steam(proc, uid, netns):
    seen = set()
    try:
        for p in proc.iterdir():
            if not p.name.isascii() or not p.name.isdecimal():
                continue
            try:
                if p.stat().st_uid != uid or (p / "comm").read_bytes() != b"steam\n":
                    continue
                exe = os.readlink(p / "exe").removesuffix(" (deleted)")
                if os.path.basename(exe) != "steam":
                    continue
                ns = os.readlink(p / "ns/net")
                if not re.fullmatch(r"net:\[[0-9]+\]", ns):
                    return "unknown"
                seen.add(ns == netns)
            except (FileNotFoundError, ProcessLookupError):
                continue
    except OSError:
        return "unknown"
    if len(seen) == 2:
        return "mixed"
    if seen:
        return "same" if True in seen else "different"
    return "not_running"


def _snapshot(prefix, proc, runtime, uid):
    key = hashlib.sha256(os.fsencode(prefix)).hexdigest()[:16]
    session = runtime / "shorin-proton-wrapper" / "sessions" / key
    try:
        info = session.lstat()
    except FileNotFoundError:
        return _unknown("absent")
    except OSError:
        return _unknown()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid:
        return _unknown()
    try:
        (session / "keeper.pid").lstat()
    except FileNotFoundError:
        # The wrapper leaves the session directory and lock after shutdown.
        try:
            if not any(p.name in ("netns", "userns", "keeper.pid.tmp") for p in session.iterdir()):
                return _unknown("absent")
        except OSError:
            pass
        return _unknown()
    except OSError:
        return _unknown()
    try:
        identity = _keeper(proc, session, uid)
        p, _, netns = identity
        result = _unknown("verified")
        try:
            result["uu_device"], result["uu_rx_bytes"], result["uu_tx_bytes"] = _device(p)
        except (OSError, ValueError):
            pass
        try:
            count = _routes(p)
            if count and result["uu_device"] == "absent":
                # The link changed between the two kernel snapshots.
                result["uu_device"] = "unknown"
            else:
                result["uu_ipv4_routes"] = count
        except (OSError, ValueError):
            pass
        result["steam_network"] = _steam(proc, uid, netns)
        if identity == _keeper(proc, session, uid):
            return result
    except (OSError, ValueError, IndexError):
        pass
    return _unknown()


def snapshot(prefix: Path) -> dict:
    """Report sampled main IPv4 routes, link counters and native Steam placement.

    An absent session has no live keeper metadata. Unverified observations are
    unknown. A present link, stored routes or changing counters alone cannot
    establish a successful connection to an acceleration node.
    """
    uid = os.getuid()
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/shorin-proton-wrapper-{uid}")
    try:
        prefix = Path(prefix).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return _unknown()
    return _snapshot(prefix, Path("/proc"), runtime, uid)
