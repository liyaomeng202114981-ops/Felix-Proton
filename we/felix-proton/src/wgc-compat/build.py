#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
# Copyright 2026 Felix Li, with OpenAI Codex assistance.
"""Build outside the installed runner. Requires the pinned SteamRT4 SDK and pefile."""
import argparse
import os
from pathlib import Path
import re
import subprocess

import pefile

SDK = ("registry.gitlab.steamos.cloud/proton/steamrt4/sdk/x86_64@sha256:"
       "6c1789cad862fd8ed9d46d71bbf8752bb7cb2336ab5e9680c0f0e3e7c88d77f1")
SOURCE = Path(__file__).resolve().parent
BRIDGES = ("CreateDirect3D11DeviceFromDXGIDevice", "CreateDirect3D11SurfaceFromDXGISurface")


def forwarder(base_dll, out):
    with pefile.PE(str(base_dll)) as image:
        if image.FILE_HEADER.Machine != pefile.MACHINE_TYPE["IMAGE_FILE_MACHINE_AMD64"]:
            raise ValueError("Expected an x86-64 D3D11 provider")
        symbols = image.DIRECTORY_ENTRY_EXPORT.symbols
        exports = ["LIBRARY d3d11", "EXPORTS"]
        last = 0
        for symbol in symbols:
            name = symbol.name.decode("ascii") if symbol.name else ""
            if not re.fullmatch(r"[a-zA-Z_][a-zA-Z_0-9]*", name) or name in BRIDGES:
                raise ValueError("Expected named D3D11 exports without the two WinRT bridges")
            exports.append(f"    {name}=felix_d3d11_base.{name} @{symbol.ordinal}")
            last = max(last, symbol.ordinal)
        if not last:
            raise ValueError("Missing D3D11 exports")
        for ordinal, name in enumerate(BRIDGES, last + 1):
            exports.append(f"    {name}=felix_wgc.{name} @{ordinal}")
    (out / "d3d11.def").write_text("\n".join(exports) + "\n", encoding="ascii")


def build(out, args):
    command = ["docker", "run", "--rm", "--pull", "never", "--network", "none",
               "--read-only", "--tmpfs", "/tmp", "--cap-drop", "ALL",
               "--security-opt", "no-new-privileges", "--user", f"{os.getuid()}:{os.getgid()}",
               "-v", f"{out}:/out", "-v", f"{SOURCE}:/src:ro", SDK,
               "x86_64-w64-mingw32-g++-posix"]
    subprocess.run(command + args, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_dll", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--in-app", action="store_true", help="also build the companion capture helpers")
    args = parser.parse_args()
    base, out = args.base_dll.resolve(strict=True), args.out.resolve()
    out.mkdir(mode=0o700, exist_ok=True)
    forwarder(base, out)
    common = ["-std=c++17", "-O2", "-Wall", "-Wextra", "-static"]
    libs = ["-lruntimeobject", "-lole32", "-lgdi32", "-luuid"]
    build(out, common + ["-Wno-missing-field-initializers", "-Wno-cast-function-type", "-shared", "/src/wgc.cpp",
                         "/src/felix_wgc.def", "-o", "/out/felix_wgc.dll"] + libs)
    build(out, ["-shared", "/out/d3d11.def", "-o", "/out/d3d11.dll"])
    build(out, common + ["-Wno-cast-function-type", "-municode", "/src/probe.cpp",
                         "-o", "/out/probe.exe", "-ld3d11"] + libs)
    if args.in_app:
        gui = common + ["-Werror", "-municode", "-mwindows"]
        build(out, gui + ["/src/inapp_actions.cpp",
                              "-o", "/out/inapp_actions.exe", "-loleaut32",
                              "-lole32", "-luuid", "-luiautomationcore", "-lshell32"])
        build(out, gui + ["/src/window_proxy.cpp", "-o", "/out/felix-wgc-window.exe"])


if __name__ == "__main__":
    main()
