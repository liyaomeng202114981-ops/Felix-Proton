#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Fetch hash-locked upstream sources and build their deterministic source bundle.

This only reads source archives. It never extracts or executes component code,
builds Wine, changes an installed runner, or accesses a user prefix.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import urllib.parse
import urllib.request

HERE = Path(__file__).resolve().parent
BUNDLE = "felix-proton-test.1-dependency-sources.tar.zst"
TOP = "felix-proton-test.1-dependency-sources"
MAIN_ASSETS = (
    ("felix-proton-uu-test-0.1.0-test.1.tar.zst", 470301310,
     "320d1a9fce1bd4a885c6cc88c35db50411234c0e5f477e167e15460d09362fea", "historical binary repack"),
    ("felix-proton-uu-test.1-modified-wine-source.tar.zst", 54836809,
     "af0dc50ef991da42aa2c1ccd56eae4f06b7f12a0dd6b38befc00943af86d19da", "complete patched Wine and historical module build recipes"),
    ("we-proton-4617d991-build-source.tar.zst", 109322604,
     "89920aaa31d0e317e9f0b4752a4d35687261f8ba7002e2df39881394fa0e261f", "base build project, complete patches and rules"),
    ("we-proton-ge11-11-31-source.tar.xz", 73409052,
     "7b8e8a47a818865c7be8d90020b1f5774a87bc161c381b055ebe47209845f3c5", "original upstream patched components, including DXVK/vkd3d nested sources"),
)


class SourceError(ValueError):
    pass


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def load_lock(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != "felix-runtime-dependency-sources-v1":
        raise SourceError("Unknown source-lock schema")
    entries = data.get("archives")
    if not isinstance(entries, list) or not entries:
        raise SourceError("Source lock has no archives")
    names = set()
    for item in entries:
        name = item.get("file", "")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", name) or name in names:
            raise SourceError("Unsafe or duplicate source filename")
        names.add(name)
        if not re.fullmatch(r"[0-9a-f]{64}", item.get("sha256", "")):
            raise SourceError("Missing source SHA-256: " + name)
        if not isinstance(item.get("bytes"), int) or item["bytes"] <= 0:
            raise SourceError("Missing source length: " + name)
        url = urllib.parse.urlsplit(item.get("url", ""))
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise SourceError("Source URL must be public HTTPS without credentials")
        if not item.get("revision"):
            raise SourceError("Missing source revision")
    return data


def check_file(path: Path, entry: dict) -> None:
    if path.is_symlink() or not path.is_file():
        raise SourceError("Source must be a regular file: " + entry["file"])
    if path.stat().st_size != entry["bytes"] or digest(path) != entry["sha256"]:
        raise SourceError("Source checksum mismatch: " + entry["file"])


def fetch(cache: Path, lock: dict) -> None:
    if cache.is_symlink():
        raise SourceError("Cache must not be a symlink")
    cache.mkdir(parents=True, exist_ok=True)
    for item in lock["archives"]:
        target = cache / item["file"]
        if not os.path.lexists(target):
            with tempfile.NamedTemporaryFile(prefix=".source-", dir=cache, delete=False) as temporary:
                name = Path(temporary.name)
                try:
                    request = urllib.request.Request(item["url"], headers={"User-Agent": "Felix-Proton-source-materials/1"})
                    with urllib.request.urlopen(request, timeout=120) as response:
                        for block in iter(lambda: response.read(1024 * 1024), b""):
                            temporary.write(block)
                    temporary.flush()
                    check_file(name, item)
                    if os.path.lexists(target):
                        raise SourceError("Source appeared during download: " + item["file"])
                    name.replace(target)
                finally:
                    name.unlink(missing_ok=True)
        check_file(target, item)


def json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _add(archive: tarfile.TarFile, name: str, data: bytes | Path, epoch: int) -> None:
    import io
    member = tarfile.TarInfo(TOP + "/" + name)
    member.mode = 0o644
    member.mtime = epoch
    if isinstance(data, Path):
        member.size = data.stat().st_size
        with data.open("rb") as stream:
            archive.addfile(member, stream)
    else:
        member.size = len(data)
        archive.addfile(member, io.BytesIO(data))


def build(cache: Path, output: Path, lock_path: Path = HERE / "SOURCE_LOCK.json", epoch: int = 0) -> dict:
    lock = load_lock(lock_path)
    if epoch < 0 or cache.is_symlink() or output.is_symlink():
        raise SourceError("Invalid cache, output or source date")
    for item in lock["archives"]:
        check_file(cache / item["file"], item)
    notices = (HERE / "THIRD_PARTY_NOTICES.md").read_bytes()
    readme = (HERE / "README.md").read_bytes()
    output.mkdir(parents=True, exist_ok=True)
    destinations = [output / name for name in (BUNDLE, "SOURCE_INDEX.json", "THIRD_PARTY_NOTICES.md")]
    if any(os.path.lexists(path) for path in destinations):
        raise SourceError("Refusing to overwrite source release files")
    with tempfile.TemporaryDirectory(prefix=".source-bundle-", dir=output) as temp:
        temporary = Path(temp) / BUNDLE
        with temporary.open("wb") as target:
            with subprocess.Popen(["zstd", "-q", "-T2", "-1", "-c"], stdin=subprocess.PIPE, stdout=target) as compressor:
                try:
                    with compressor.stdin, tarfile.open(fileobj=compressor.stdin, mode="w|", format=tarfile.PAX_FORMAT) as archive:
                        _add(archive, "SOURCE_LOCK.json", json_bytes(lock), epoch)
                        _add(archive, "THIRD_PARTY_NOTICES.md", notices, epoch)
                        _add(archive, "README.md", readme, epoch)
                        sums = "".join(item["sha256"] + "  archives/" + item["file"] + "\n" for item in sorted(lock["archives"], key=lambda x: x["file"]))
                        _add(archive, "SHA256SUMS", sums.encode("ascii"), epoch)
                        for item in sorted(lock["archives"], key=lambda x: x["file"]):
                            _add(archive, "archives/" + item["file"], cache / item["file"], epoch)
                except BaseException:
                    compressor.kill()
                    compressor.wait()
                    raise
                if compressor.wait():
                    raise SourceError("Source compression failed")
        bundle = {"file": BUNDLE, "bytes": temporary.stat().st_size, "sha256": digest(temporary), "archives": len(lock["archives"])}
        index = {
            "schema": "felix-proton-test.1-source-index-v1",
            "scope": "Corresponding materials for the x86-64 historical test.1 binary repack; not a new complete build or a bit-identical full-build claim",
            "fixed_assets": [{"file": name, "bytes": size, "sha256": sha, "purpose": purpose} for name, size, sha, purpose in MAIN_ASSETS],
            "dependency_bundle": bundle,
            "dependency_lock": lock,
            "source_date_epoch": epoch,
        }
        temporary.replace(output / BUNDLE)
        (output / "SOURCE_INDEX.json").write_bytes(json_bytes(index))
        (output / "THIRD_PARTY_NOTICES.md").write_bytes(notices)
    return {"dependency_bundle": bundle, "source_index_sha256": digest(output / "SOURCE_INDEX.json"), "notices_sha256": digest(output / "THIRD_PARTY_NOTICES.md")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--lock", type=Path, default=HERE / "SOURCE_LOCK.json")
    parser.add_argument("--fetch", action="store_true", help="Fetch only missing archives, then verify every pinned digest")
    parser.add_argument("--source-date-epoch", type=int, default=0)
    args = parser.parse_args()
    if args.fetch:
        fetch(args.cache, load_lock(args.lock))
    print(json.dumps(build(args.cache, args.output_dir, args.lock, args.source_date_epoch), sort_keys=True))


if __name__ == "__main__":
    main()
