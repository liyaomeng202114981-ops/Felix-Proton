#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Build the reviewed setup-source kit; runtime and corresponding sources are separate assets."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import tarfile
import tempfile

VERSION = "0.1.0-preview.1"
KIT = "felix-proton-setup-" + VERSION
MAX_SOURCE = 4 * 1024 * 1024


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(part)
    return result.hexdigest()


def read_sources(root, inventory):
    paths = json.loads(inventory.read_text())
    if not isinstance(paths, list) or not paths or len(paths) != len(set(paths)):
        raise ValueError("Source inventory must be a nonempty unique list")
    result = {}
    for name in paths:
        if (not isinstance(name, str) or name.startswith("/") or "\\" in name or
                any(p in ("", ".", "..", ".git", "__pycache__", "archive", "evidence", "releases")
                    for p in name.split("/")) or Path(name).suffix in (".log", ".jsonl", ".pyc", ".exe")):
            raise ValueError("Unsafe source path")
        path = root / name
        for parent in (path, *path.parents):
            if parent == root:
                break
            if parent.is_symlink():
                raise ValueError("Symlink in source inventory: " + name)
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_SOURCE:
            raise ValueError("Not a bounded regular source: " + name)
        result[name] = path.read_bytes()
    for required in ("src/setup-tool/setup.py", "src/setup-tool/downloads.json",
                     "src/native-ux/enable.py", "src/pairing-tool/app.py", "packaging/fromzero/INSTALL.md"):
        if required not in result:
            raise ValueError("Missing required setup source: " + required)
    if result["src/pairing-tool/lib/desktop.py"] != result["src/native-ux/desktop.py"]:
        raise ValueError("Bundled pairing desktop module differs from canonical source")
    return result


def build(root, inventory, output):
    root = root.resolve(strict=True)
    files = read_sources(root, inventory)
    manifest = {"schema": "felix-proton-setup-build-v1", "version": VERSION,
                "source_date_epoch": 0,
                "source_files": {n: hashlib.sha256(data).hexdigest() for n, data in sorted(files.items())},
                "runner": "Historical SHA-locked test.1 repack, supplied as a separate release asset",
                "scope": "Fresh prefix setup and original Steam/UU launch integration; no client or account data"}
    info = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    payload = dict(files)
    payload["README.md"] = files["packaging/fromzero/INSTALL.md"]
    payload["LICENSE"] = files["src/native-ux/LICENSE"]
    payload["BUILDINFO.json"] = info
    output.mkdir(parents=True, exist_ok=True)
    target = output / (KIT + "-linux.tar.gz")
    if target.is_symlink() or target.exists() and not target.is_file():
        raise ValueError("Unsafe archive destination")
    with tempfile.NamedTemporaryFile(dir=output, delete=False) as staged:
        temporary = Path(staged.name)
        try:
            with gzip.GzipFile(filename="", fileobj=staged, mode="wb", mtime=0, compresslevel=9) as compressed:
                with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as archive:
                    for name, data in sorted(payload.items()):
                        member = tarfile.TarInfo(KIT + "/" + name)
                        member.mode, member.mtime, member.uid, member.gid = 0o644, 0, 0, 0
                        member.size = len(data)
                        archive.addfile(member, io.BytesIO(data))
            staged.flush()
            os.fsync(staged.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    (output / "SETUP_BUILDINFO.json").write_bytes(info)
    return {"archive": target.name, "sha256": digest(target), "bytes": target.stat().st_size,
            "source_files": len(files)}


def checksums(folder):
    paths = sorted(p for p in folder.iterdir() if p.is_file() and p.name != "SHA256SUMS")
    for path in paths:
        if path.is_symlink() or not re.fullmatch(r"[A-Za-z0-9._-]+", path.name):
            raise ValueError("Unsafe release asset filename")
    (folder / "SHA256SUMS").write_text("".join(digest(p) + "  " + p.name + "\n" for p in paths), encoding="ascii")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-tree", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.public_tree, args.inventory, args.output_dir)))


if __name__ == "__main__":
    main()
