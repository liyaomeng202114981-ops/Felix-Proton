#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Felix Li, with OpenAI Codex assistance.
"""Build only the pairing tool from an explicit, reproducible source allowlist.

No installed runner, prefix, account configuration or host application is read.
Python remains source; the portable archive includes its matching tests and build
script. The optional Debian package installs only this tool's files and entry.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile

sys.dont_write_bytecode = True

ICON_FILE = "assets/felix-pairing-round-v5.svg"
ICON_NAME = "felix-pairing-round-v5"
DESKTOP_ID = "io.github.felixproton.Pairing.desktop"
SOURCE_FILES = (
    "app.py", "backend.py", "catalog.py", "install.py", "lib/desktop.py",
    ICON_FILE, "VERSION", "LICENSE", "COPYRIGHT", "README.md", "TEST_RESULTS.md",
    "RELEASE_NOTES.md", "build_release.py", "test_backend.py", "test_catalog.py",
    "test_release.py", "smoke_ui.py",
)
VERSION_PATTERN = re.compile(r"([0-9]+\.[0-9]+\.[0-9]+)(?:-preview\.([1-9][0-9]*))?\Z")
MAX_SOURCE_FILE = 2 * 1024 * 1024


class BuildError(RuntimeError):
    pass


def _epoch(value=None):
    if value is None:
        value = os.environ.get("SOURCE_DATE_EPOCH", "0")
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise BuildError("SOURCE_DATE_EPOCH must be an integer") from None
    if result < 0 or result > 0xFFFFFFFF:
        raise BuildError("SOURCE_DATE_EPOCH must fit an unsigned 32-bit timestamp")
    return result


def _regular_source(source, relative):
    path = source / relative
    try:
        info = path.lstat()
    except FileNotFoundError:
        raise BuildError("Missing release source: " + relative) from None
    # Reject symlinked parent directories as well as a symlinked final file.
    current = path
    while current != source:
        if current.is_symlink():
            raise BuildError("Release sources cannot be symlinks: " + relative)
        current = current.parent
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_SOURCE_FILE:
        raise BuildError("Release source is not a bounded regular file: " + relative)
    return path.read_bytes()


def _version(data):
    try:
        version = data.decode("ascii").strip()
    except UnicodeError:
        raise BuildError("VERSION must contain an ASCII release version") from None
    match = VERSION_PATTERN.fullmatch(version)
    if match is None:
        raise BuildError("VERSION must be x.y.z or x.y.z-preview.N")
    debian = match[1] + ("~preview" + match[2] if match[2] else "")
    return version, debian


def _json_bytes(data):
    return (json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _publish(path, data, mode=0o644):
    if os.path.lexists(path) and (path.is_symlink() or not path.is_file()):
        raise BuildError("Output destination is not a regular file: " + path.name)
    fd, name = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _portable(root_name, payload, epoch):
    output = io.BytesIO()
    directories = {root_name}
    for relative in payload:
        parent = Path(relative).parent
        while parent != Path("."):
            directories.add(root_name + "/" + parent.as_posix())
            parent = parent.parent
    with gzip.GzipFile(filename="", mode="wb", fileobj=output, compresslevel=9, mtime=epoch) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
            for directory in sorted(directories):
                entry = tarfile.TarInfo(directory)
                entry.type = tarfile.DIRTYPE
                entry.mode, entry.mtime = 0o755, epoch
                archive.addfile(entry)
            for relative, data in sorted(payload.items()):
                entry = tarfile.TarInfo(root_name + "/" + relative)
                entry.size, entry.mode, entry.mtime = len(data), 0o644, epoch
                archive.addfile(entry, io.BytesIO(data))
    return output.getvalue()


def _deb(output, name, payload, epoch, debian_version):
    executable = shutil.which("dpkg-deb")
    if executable is None:
        raise BuildError("dpkg-deb is required for .deb output; use --no-deb for the portable archive only")
    with tempfile.TemporaryDirectory(prefix=".pairing-deb-", dir=output) as temporary:
        stage = Path(temporary) / "package"
        files = {"usr/share/felix-pairing-tool/" + relative: data for relative, data in payload.items()}
        files["usr/bin/felix-pairing"] = (
            b'#!/bin/sh\nexec /usr/bin/python3 -B /usr/share/felix-pairing-tool/app.py "$@"\n')
        files["usr/share/applications/" + DESKTOP_ID] = (
            "[Desktop Entry]\nType=Application\nName=Felix 配对\nName[en]=Felix Pairing\n"
            "Comment=Pair existing Steam and UU launcher entries\nExec=felix-pairing\n"
            "Icon=" + ICON_NAME + "\nTerminal=false\nCategories=Game;Utility;\n"
            "StartupNotify=true\nX-Felix-Pairing-Owner=Felix Pairing v1\n").encode()
        files["usr/share/icons/hicolor/scalable/apps/" + ICON_NAME + ".svg"] = payload[ICON_FILE]
        files["usr/share/doc/felix-pairing/copyright"] = payload["COPYRIGHT"] + b"\n" + payload["LICENSE"]
        for relative, data in files.items():
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(0o755 if relative == "usr/bin/felix-pairing" else 0o644)
        control = stage / "DEBIAN"
        control.mkdir()
        installed_size = math.ceil(sum(len(value) for value in files.values()) / 1024)
        (control / "control").write_text(
            "Package: felix-pairing\nVersion: " + debian_version + "\nSection: utils\nPriority: optional\n"
            "Architecture: all\nMaintainer: Felix Li\nInstalled-Size: " + str(installed_size) + "\n"
            "Depends: python3 (>= 3.10), python3-gi, gir1.2-gtk-4.0 (>= 4.10), "
            "gir1.2-adw-1 (>= 1.4), hicolor-icon-theme\n"
            "Homepage: https://github.com/liyaomeng202114981-ops/Felix-Proton\n"
            "Description: Pair existing Steam and UU launcher entries\n"
            " A small GTK tool for an already configured Felix-Proton integration.\n"
            " It preserves original application icons and uses reversible pairing.\n"
            " This package does not install a Proton runner, Steam or UU.\n", encoding="utf-8")
        (control / "md5sums").write_text("".join(
            hashlib.md5(data).hexdigest() + "  " + relative + "\n"
            for relative, data in sorted(files.items())), encoding="ascii")
        for path in sorted(stage.rglob("*"), reverse=True):
            if path.is_dir():
                path.chmod(0o755)
            os.utime(path, (epoch, epoch), follow_symlinks=False)
        stage.chmod(0o755)
        os.utime(stage, (epoch, epoch))
        destination = output / name
        if os.path.lexists(destination) and (destination.is_symlink() or not destination.is_file()):
            raise BuildError("Output destination is not a regular file: " + name)
        built = Path(temporary) / name
        env = dict(os.environ, SOURCE_DATE_EPOCH=str(epoch), DPKG_DEB_THREADS_MAX="1")
        result = subprocess.run([executable, "--build", "--root-owner-group", "-Zxz", "-z9", "--threads-max=1",
                                 str(stage), str(built)], env=env, capture_output=True, text=True)
        if result.returncode:
            raise BuildError("dpkg-deb could not build the pairing package: " + result.stderr.strip())
        _publish(destination, built.read_bytes())


def build(output_dir, *, source_dir=None, with_deb=True, epoch=None):
    """Return paths/hashes after building the explicit source payload.

    BUILDINFO describes only release sources, never absolute local paths or user
    state. SHA256SUMS covers the generated public files except itself.
    """
    source = Path(source_dir or Path(__file__).resolve().parent).absolute()
    if source.is_symlink() or not source.is_dir():
        raise BuildError("Source directory must be a real directory")
    payload = {relative: _regular_source(source, relative) for relative in SOURCE_FILES}
    version, debian = _version(payload["VERSION"])
    timestamp = _epoch(epoch)
    root_name = "felix-pairing-" + version
    info = {"schema": "felix-pairing-build-v1", "version": version,
            "source_date_epoch": timestamp, "package_root": root_name,
            "scope": "Pairing tool only; requires separately configured Felix-Proton integration",
            "source_files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(payload.items())}}
    info_bytes = _json_bytes(info)
    payload["BUILDINFO.json"] = info_bytes
    output = Path(output_dir).absolute()
    if os.path.lexists(output) and (output.is_symlink() or not output.is_dir()):
        raise BuildError("Output directory must be a real directory")
    output.mkdir(parents=True, exist_ok=True)
    if with_deb and shutil.which("dpkg-deb") is None:
        raise BuildError("dpkg-deb is required for .deb output; use --no-deb for the portable archive only")
    portable_name = root_name + "-linux.tar.gz"
    # GitHub normalizes '~' in asset filenames; keep Debian ordering only in control.
    deb_name = "felix-pairing_" + version + "_all.deb"
    _publish(output / portable_name, _portable(root_name, payload, timestamp))
    if with_deb:
        _deb(output, deb_name, payload, timestamp, debian)
    _publish(output / "BUILDINFO.json", info_bytes)
    names = sorted([portable_name, "BUILDINFO.json"] + ([deb_name] if with_deb else []))
    checksums = "".join(hashlib.sha256((output / name).read_bytes()).hexdigest() + "  " + name + "\n"
                        for name in names)
    _publish(output / "SHA256SUMS", checksums.encode("ascii"))
    return {"version": version, "tag": "felix-pairing-v" + version, "output_dir": str(output),
            "artifacts": [{"name": name, "path": str(output / name),
                           "sha256": hashlib.sha256((output / name).read_bytes()).hexdigest(),
                           "size": (output / name).stat().st_size}
                          for name in names + ["SHA256SUMS"]]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-dir", type=Path)
    parser.add_argument("--source-date-epoch", type=int)
    parser.add_argument("--no-deb", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = build(args.output_dir, source_dir=args.source_dir, with_deb=not args.no_deb,
                       epoch=args.source_date_epoch)
    except (BuildError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
