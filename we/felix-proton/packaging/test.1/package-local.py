#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Build the local Felix test.1 .tar.zst from its locked historical binary base."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
import tempfile


TOOL = "felix-proton-uu-test-0.1.0-test.1"
BASE = "we-proton-ge11-11-31-desktop-netfix2"
META = ("compatibilitytool.vdf", "felix-build.json", "version", "we-proton-build-info")
SKIP_TOP = {"README-DESKTOP-BUILD.txt", "README-NETWORK-BUILD.txt",
            "desktop-build-provenance", "network-build-provenance"}
GAME_CACHE = Path("files/lib/wine/x86_64-windows/WeGameApps")
# Digests of the independently validated, unchanged runner content. Identity
# metadata and the felix/ additions are verified separately.
BASE_INVENTORY = "5af4a6e9d1e738aa91bd3b579eadbad5dec5f2015c86d46dccc86aaae9306485"
BASE_CONTENT = "fda998268694fd3945cbaf297e6ed6176f82a247576f62c705e40efd725ee560"


def inventory(root, *, base=False):
    """Collect only ordinary files, directories, and links contained by this tree."""
    result = {}
    pending = [Path(".")]
    while pending:
        parent = pending.pop()
        for path in (root / parent).iterdir():
            name = path.relative_to(root)
            if path.name == "__pycache__" or path.name.endswith(".pyc"):
                continue
            if base and (str(name) in SKIP_TOP or str(name) in META or name == GAME_CACHE):
                continue
            mode = path.lstat().st_mode
            bits = stat.S_IMODE(mode)
            if bits & (stat.S_ISUID | stat.S_ISGID):
                raise ValueError(f"unexpected special permissions: {name}")
            if stat.S_ISLNK(mode):
                target = os.readlink(path)
                if os.path.isabs(target) or not path.resolve(strict=True).is_relative_to(root):
                    raise ValueError(f"escaping or broken symlink: {name}")
                info = ("link", bits, target)
            elif stat.S_ISDIR(mode):
                pending.append(name)
                info = ("dir", bits, "")
            elif stat.S_ISREG(mode):
                info = ("file", bits, path.stat().st_size)
            else:
                raise ValueError(f"unexpected special file: {name}")
            result[name] = info
    return result


def inventory_digest(entries):
    h = hashlib.sha256()
    for path, info in sorted(entries.items()):
        h.update(json.dumps([str(path), *info], ensure_ascii=True).encode("ascii") + b"\n")
    return h.hexdigest()


def checklist(root, platform):
    if root == platform or root.is_relative_to(platform):
        raise ValueError("use a reviewed extras directory outside the historical runner")
    entries = inventory(root)
    if not entries:
        raise ValueError("empty extras directory")
    # Real diagnostic output, user data, checkout internals and installed games
    # have no place in the curated source/docs/evidence tree.
    forbidden = {".git", "pfx", "drive_c", ".ssh", ".env", "WeGameApps", "session_logs",
                 "user.reg", "system.reg", "userdata.db", "gameprocess_log.txt", "console-linux.txt"}
    for name in entries:
        if (any(part in forbidden or part.startswith("run-20") for part in name.parts)
                or name.suffix in (".jsonl", ".pcap", ".pcapng", ".dmp", ".xlog")):
            raise ValueError(f"session or private data in extras: {name}")
        if name.suffix == ".log":
            smoke = root / name
            if (name.name != "smoke-sdk.log" or smoke.stat().st_size != 930 or
                    hashlib.sha256(smoke.read_bytes()).hexdigest() !=
                    "80004cf2d33908a1b924b89415a24d7d20671fb31c1cac1d62edee0d473cfa45"):
                raise ValueError(f"unreviewed log in extras: {name}")
    return entries


def metadata(base, meta):
    for name in META:
        if (meta / name).is_symlink() or not (meta / name).is_file():
            raise ValueError(f"missing regular metadata file: {name}")
        if (meta / name).stat().st_size > 128 * 1024:
            raise ValueError(f"unexpected metadata size: {name}")
    if (base / "version").read_text().split()[-1] != BASE:
        raise ValueError("wrong historical runner identity")
    stamp, tool_id = (meta / "version").read_text().split()
    manifest = json.loads((meta / "felix-build.json").read_text())
    info = (meta / "we-proton-build-info").read_text().splitlines()
    vdf = (meta / "compatibilitytool.vdf").read_text()
    if (tool_id != TOOL or manifest["steam_tool_id"] != TOOL or manifest["base_runner"] != BASE or
            info[:2] != [f"name: {TOOL}", f"repack-base-name: {BASE}"] or
            f'"{TOOL}"' not in vdf or f'"display_name" "{manifest["display_name"]}"' not in vdf):
        raise ValueError("inconsistent output metadata")
    return int(stamp)


def append_member(archive, arcname, path, info, stamp, content=None):
    kind, bits, value = info
    member = tarfile.TarInfo(str(arcname))
    member.mode, member.mtime = bits, stamp
    # TarInfo defaults to numeric owner/group 0 and empty owner/group names.
    if kind == "dir":
        member.type = tarfile.DIRTYPE
    elif kind == "link":
        member.type, member.linkname = tarfile.SYMTYPE, value
    elif kind == "file":
        member.size = value
        with path.open("rb") as stream:
            if content is None:
                archive.addfile(member, stream)
            else:
                digest = hashlib.sha256()
                class Reader:
                    def read(self, length):
                        data = stream.read(length)
                        digest.update(data)
                        return data
                archive.addfile(member, Reader())
                content.update(digest.digest())
        return
    archive.addfile(member)


def build(base, extras, meta, out):
    base, extras, meta = (p.resolve(strict=True) for p in (base, extras, meta))
    # Resolve only the parent to reject even dangling output symlinks.
    out = out.parent.resolve(strict=True) / out.name
    if not out.name.endswith(".tar.zst") or os.path.lexists(out):
        raise ValueError("output must be a new .tar.zst file")
    if any(out.is_relative_to(root) for root in (base, extras, meta)):
        raise ValueError("output must be outside the input trees")
    stamp = metadata(base, meta)
    entries = inventory(base, base=True)
    if inventory_digest(entries) != BASE_INVENTORY:
        raise ValueError("runner inventory differs from the validated historical base")
    overlay = checklist(extras, base)
    # Compress into a private temporary file. Publish atomically without replacing
    # an existing destination, including one created by another process.
    with tempfile.NamedTemporaryFile(dir=out.parent, prefix=".felix-pack-") as tmp:
        with subprocess.Popen(["zstd", "-q", "-T2", "-8", "-c"], stdin=subprocess.PIPE,
                              stdout=tmp, env={k:v for k,v in os.environ.items() if k != "ZSTD_CLEVEL"}) as zstd:
            try:
                with zstd.stdin, tarfile.open(fileobj=zstd.stdin, mode="w|", format=tarfile.GNU_FORMAT) as archive:
                    top = Path(TOOL)
                    append_member(archive, top, None, ("dir", 0o755, ""), stamp)
                    content = hashlib.sha256()
                    for name, info in sorted(entries.items()):
                        append_member(archive, top / name, base / name, info, stamp, content)
                    if content.hexdigest() != BASE_CONTENT:
                        raise ValueError("runner file contents differ from the validated historical base")
                    for name in META:
                        path = meta / name
                        append_member(archive, top / name, path, ("file", 0o644, path.stat().st_size), stamp)
                    append_member(archive, top / "felix", None, ("dir", 0o755, ""), stamp)
                    for name, info in sorted(overlay.items()):
                        append_member(archive, top / "felix" / name, extras / name, info, stamp)
            except BaseException:
                zstd.kill()
                raise
            if zstd.wait():
                raise ValueError("zstd failed; no package published")
        os.fsync(tmp.fileno())
        os.link(tmp.name, out)
    print(out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key, help_text in (("base", "historical netfix2 runner directory"),
                           ("extras", "complete reviewed contents of felix/"),
                           ("metadata", "directory containing the four test.1 identity files"),
                           ("output", "new .tar.zst file in an existing directory")):
        parser.add_argument("--" + key, type=Path, required=True, help=help_text)
    args = parser.parse_args()
    try:
        build(args.base, args.extras, args.metadata, args.output)
    except (KeyError, IndexError, OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"package-local: {error}\n")


if __name__ == "__main__":
    main()
