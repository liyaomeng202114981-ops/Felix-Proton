# SPDX-License-Identifier: BSD-3-Clause
"""Fixed diagnostic event vocabulary for Wine output and UU's three network logs."""
from __future__ import annotations

from dataclasses import dataclass
import codecs
import os
from pathlib import Path
import re
import stat


LOG_DIR = Path("pfx/drive_c/users/steamuser/AppData/Roaming/Netease/UU")
LOG_NAMES = ("uu", "uu_tun", "uu_proxy")
MAX_LINE = 8192
READ_BUDGET = 64 * 1024  # per file and poll; report any omitted prefix
MAX_EVENTS = 48  # per file, plus metadata
SAMPLE_SIZE = 1024

# Match only fixed phrases; the actual subject, target, address, paths and
# command line are never fields. A text mention alone does not establish UI state.
_RULES = tuple((kind, re.compile(pattern, re.I)) for kind, pattern in (
    ("network_permission_denied", r"(?:sendmsg|sendto|try_send|socket|winsock).{0,160}(?:permission denied|access (?:is )?denied|eacces)"),
    ("network_connection_refused", r"connection refused|连接被拒绝"),
    ("network_unreachable", r"network is unreachable|no route to host|网络不可达"),
    ("network_timeout_mentioned", r"(?:connect(?:ion)?|socket|network|request).{0,40}(?:timed? out|timeout)|(?:连接|网络|请求)超时"),
    ("client_node_unsupported_mentioned", r"当前系统不支持连接该节点|system does not support (?:connecting to )?(?:this|the) node"),
    ("client_stop_mentioned", r"停止加速|断开加速|\b(?:stop|disconnect)(?:ping)?[ _-]+(?:acceleration|boost)\b|\bstopboost\b"),
    ("client_start_mentioned", r"开始加速|启动加速|\bstart(?:ing)?[ _-]+(?:acceleration|boost)\b|\bstartboost\b"),
    ("client_success_mentioned", r"加速成功|\b(?:acceleration|boost) (?:succeeded|successful)\b"),
    ("client_target_selection_mentioned", r"选择游戏|切换游戏|\b(?:select(?:ed)?|switch)[ _-]+game\b|\bselectgame\b"),
    ("client_node_selection_mentioned", r"选择节点|切换节点|节点列表|\b(?:node[ _-]+list|select[ _-]+node)\b"),
    ("client_route_mode_mentioned", r"路由模式|\b(?:route|routing)[ _-]+mode\b"),
    ("route_create_call", r"\b(?:CreateIpForwardEntry2?|SetIpForwardEntry2?)\b"),
    ("route_delete_call", r"\bDeleteIpForwardEntry2?\b"),
    ("wine_network_warning", r"\b(?:warn|fixme):(?:winsock|iphlpapi|nsi|wintun):"),
    ("wine_error", r"\berr:[a-z0-9_]+:"),
    ("launcher_session_network_mentioned", r"session: network namespace of keeper"),
))
_WINTUN = re.compile(r"\bWintun(OpenAdapter|CreateAdapter|StartSession|EndSession|CloseAdapter)\b", re.I)
_WINTUN_TYPES = {verb.lower(): "wintun_" + name + "_call" for verb, name in (
    ("OpenAdapter", "open_adapter"), ("CreateAdapter", "create_adapter"),
    ("StartSession", "start_session"), ("EndSession", "end_session"), ("CloseAdapter", "close_adapter"))}
_CODE = re.compile(r'(?<![\w/?&])(?:error[ _-]?code|last[ _-]?error|errno|错误码|错误代码)["\']?\s*[:=：]\s*["\']?([0-9]{1,5})(?![\w.])', re.I)
# Keep only documented/well-known network error values following an explicit
# error-code label. Unknown numbers could double as user identifiers.
_SAFE_CODES = frozenset((5, 13, 50, 87, 101, 104, 110, 111, 113, 120, 121, 995,
                        10013, 10049, 10050, 10051, 10053, 10054, 10055, 10060, 10061,
                        10065, 11001, 11002, 11003, 11004, 12002, 12007, 12029, 12030, 50004))


def classify_line(line: bytes) -> dict | None:
    """Classify one bounded line; returned strings are exclusively constants."""
    if len(line) > MAX_LINE or b"\0" in line:
        return None
    text = line.decode("utf-8", "replace")
    verb = _WINTUN.search(text)
    kind = (_WINTUN_TYPES[verb.group(1).lower()] if verb else
            next((name for name, pattern in _RULES if pattern.search(text)), None))
    code = _CODE.search(text)
    if not kind and not code:
        return None
    event = {"type": kind or "error_code_mentioned"}
    if code and int(code.group(1)) in _SAFE_CODES:
        event["code"] = int(code.group(1))
    return event


def _format(sample: bytes) -> str:
    if not sample:
        return "empty"
    if len(sample.strip()) >= 32 and re.fullmatch(rb"[\da-fA-F\r\n]+", sample):
        return "opaque_hex"
    if b"\0" in sample or any(c < 32 and c not in (9, 10, 13) for c in sample):
        return "opaque_binary"
    try:
        codecs.getincrementaldecoder("utf-8")().decode(sample, final=False)
    except UnicodeDecodeError:
        return "opaque_binary"
    return "text"


@dataclass
class _Cursor:
    identity: tuple[int, int] | None = None
    offset: int = 0
    format: str = "empty"
    remainder: bytes = b""
    discard_line: bool = False
    state: str = ""


class ClientLogTail:
    """Follow exact UU .log basenames. The baseline is taken at construction.

    Text lines are classified only for new bytes. Binary/hex content reports
    byte growth, not decoded text. Missing/inaccessible logs never stop peers.
    """
    def __init__(self, prefix: Path):
        self.prefix = Path(prefix)
        self.cursors = {name: _Cursor() for name in LOG_NAMES}
        self._initial = self._poll(baseline=True)

    def _directory_fd(self):
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
        fd = os.open(self.prefix, flags)
        try:
            for part in LOG_DIR.parts:
                child = os.open(part, flags | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            return fd
        except BaseException:
            os.close(fd)
            raise

    def poll(self) -> list[dict]:
        initial, self._initial = self._initial, []
        return initial + self._poll(baseline=False)

    def _unavailable(self, name, kind):
        same = self.cursors[name].state == kind
        self.cursors[name] = _Cursor(state=kind)
        return [] if same else [{"type": kind, "log": name}]

    def _poll(self, baseline):
        events = []
        try:
            directory = self._directory_fd()
        except OSError as error:
            kind = "client_log_missing" if isinstance(error, FileNotFoundError) else "client_log_unavailable"
            for name in LOG_NAMES:
                events.extend(self._unavailable(name, kind))
            return events
        try:
            for name in LOG_NAMES:
                try:
                    fd = os.open(name + ".log", os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
                                 dir_fd=directory)
                    try:
                        st = os.fstat(fd)
                        if stat.S_ISREG(st.st_mode):
                            rows = self._read(name, fd, st, baseline)
                        else:
                            rows = self._unavailable(name, "client_log_unavailable")
                        events.extend(rows)
                    finally:
                        os.close(fd)
                except OSError as error:
                    kind = "client_log_missing" if isinstance(error, FileNotFoundError) else "client_log_unavailable"
                    events.extend(self._unavailable(name, kind))
        finally:
            os.close(directory)
        return events

    def _read(self, name, fd, st, baseline):
        cursor = self.cursors[name]
        size = st.st_size
        identity = (st.st_dev, st.st_ino)
        rows = []
        change = None
        if baseline:
            change = "client_log_baseline"
        elif cursor.state == "client_log_unavailable":
            # Its previous bytes could predate this diagnostic session.
            change = "client_log_resumed"
        elif cursor.identity is None:
            change = "client_log_appeared"
        elif cursor.identity != identity:
            change = "client_log_rotated"
        elif size < cursor.offset:
            change = "client_log_truncated"
        if change:
            skip_existing = baseline or change == "client_log_resumed"
            cursor = _Cursor(identity=identity, offset=size if skip_existing else 0,
                             format=_format(os.pread(fd, min(size, SAMPLE_SIZE), 0)), state="present")
            self.cursors[name] = cursor
            rows.append({"type": change, "log": name, "format": cursor.format, "offset": cursor.offset, "size": size})
            if skip_existing and size and cursor.format == "text":
                cursor.discard_line = os.pread(fd, 1, size - 1) != b"\n"
        if cursor.offset >= size:
            return rows
        if cursor.format == "empty":
            cursor.format = _format(os.pread(fd, min(size, SAMPLE_SIZE), 0))
        start = cursor.offset
        if cursor.format in ("opaque_hex", "opaque_binary"):
            cursor.offset = size
        else:
            if size - start > READ_BUDGET:
                start = size - READ_BUDGET
                rows.append({"type": "client_log_gap", "log": name, "from_offset": cursor.offset, "to_offset": start})
                cursor.remainder = b""
                cursor.discard_line = os.pread(fd, 1, start - 1) != b"\n"
            data = os.pread(fd, size - start, start)
            cursor.offset = start + len(data)
            lines = (cursor.remainder + data).split(b"\n")
            cursor.remainder = lines.pop()
            if cursor.discard_line and lines:
                lines.pop(0)
                cursor.discard_line = False
            omitted = 0
            emitted = 0
            for line in lines:
                event = classify_line(line)
                if event:
                    if emitted < MAX_EVENTS:
                        rows.append({"log": name, **event})
                        emitted += 1
                    else:
                        omitted += 1
            if omitted:
                rows.append({"type": "client_log_events_limited", "log": name, "count": omitted})
            if len(cursor.remainder) > MAX_LINE:
                cursor.discard_line = True
            if cursor.discard_line:
                cursor.remainder = b""
        rows.append({"type": "client_log_growth", "log": name, "format": cursor.format,
                     "from_offset": start, "to_offset": cursor.offset})
        return rows
