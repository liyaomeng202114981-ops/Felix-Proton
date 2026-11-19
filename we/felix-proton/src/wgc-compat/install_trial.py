#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
# Copyright 2026 Felix Li, with OpenAI Codex assistance.
"""Stage the prototype in an already-initialized, disposable x64 Proton prefix."""
import argparse
import filecmp
import os
from pathlib import Path
import shutil
import subprocess

CLASSES = ("GraphicsCaptureItem", "Direct3D11CaptureFramePool", "GraphicsCaptureSession")


def inside(path, directory):
    path.resolve().relative_to(directory)
    return path


def stage_files(root, prefix, base_dll, system32):
    original = system32 / "d3d11.dll"
    forwarder = inside(root / original.name, root)
    if not (filecmp.cmp(original, base_dll, shallow=False) or
            filecmp.cmp(original, forwarder, shallow=False)):
        raise ValueError("Unexpected D3D11 provider. Use a fresh trial prefix.")
    files = {
        system32 / "felix_d3d11_base.dll": base_dll,
        system32 / "felix_wgc.dll": inside(root / "felix_wgc.dll", root),
        original: forwarder,
    }
    for target, source in files.items():
        tmp = inside(target.with_suffix(".trial-tmp"), prefix)
        shutil.copyfile(source, tmp)
        os.replace(tmp, target)


def register(root, prefix, proton):
    lines = ["Windows Registry Editor Version 5.00", ""]
    for name in CLASSES:
        key = (r"HKEY_LOCAL_MACHINE\Software\Microsoft\WindowsRuntime\ActivatableClassId"
               f"\\Windows.Graphics.Capture.{name}")
        lines += [f"[{key}]", r'"DllPath"="C:\\windows\\system32\\felix_wgc.dll"', ""]
    path = root / "wgc.reg"
    path.write_text("\r\n".join(lines), encoding="ascii")
    windows_path = "Z:" + str(path).replace("/", "\\")
    wrapper = Path.home() / ".local/bin/shorin-proton-wrapper"
    subprocess.run([str(wrapper), "--prefix", str(prefix), "--runner", str(proton),
                    str(prefix / "pfx/drive_c/windows/regedit.exe"), "/S", windows_path], check=True,
                   env=os.environ | {"WINEDEBUG": "-all"})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trial_dir", type=Path)
    parser.add_argument("prefix", choices=("probe-prefix", "companion-prefix"))
    args = parser.parse_args()
    root = args.trial_dir.resolve(strict=True)
    if not root.name.startswith(".wgc-prototype-"):
        raise ValueError("Use a dedicated .wgc-prototype-* trial directory.")
    prefix = inside(root / args.prefix, root).resolve(strict=True)
    if prefix != root / args.prefix:
        raise ValueError("Expected a direct trial prefix")
    runner = inside(root / "runner", root).resolve(strict=True)
    if runner != root / "runner":
        raise ValueError("Expected an independent runner copy")
    system32 = inside(prefix / "pfx/drive_c/windows/system32", prefix)
    dxvk_dll = inside(runner / "files/lib/wine/dxvk/x86_64-windows/d3d11.dll", runner)
    base_dll = inside(dxvk_dll.with_name("felix_d3d11_base.dll"), runner)
    forwarder = inside(root / "d3d11.dll", root)
    if not base_dll.exists():
        if filecmp.cmp(dxvk_dll, forwarder, shallow=False):
            raise ValueError("Missing original DXVK payload in candidate")
        shutil.copyfile(dxvk_dll, base_dll)
    if not any(filecmp.cmp(dxvk_dll, valid, shallow=False) for valid in (base_dll, forwarder)):
        raise ValueError("Unexpected provider in candidate")
    stage_files(root, prefix, base_dll, system32)
    tmp = inside(dxvk_dll.with_suffix(".trial-tmp"), runner)
    shutil.copyfile(forwarder, tmp)
    os.replace(tmp, dxvk_dll)
    register(root, prefix, inside(runner / "proton", runner))


if __name__ == "__main__":
    main()
