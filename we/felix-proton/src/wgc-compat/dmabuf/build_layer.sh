#!/bin/sh
# SPDX-License-Identifier: BSD-3-Clause
set -eu
out="$(realpath -m "$1")"
cd "$(dirname "$0")"
mkdir -p "$out"
glslang="${GLSLANG_VALIDATOR:-glslangValidator}"
"$glslang" -V crop.vert -o "$out/crop.vert.spv"
"$glslang" -V crop.frag -o "$out/crop.frag.spv"
python3 - "$out" <<'PY'
from pathlib import Path
import struct
import sys

directory = Path(sys.argv[1])
with (directory / "shaders.h").open("w") as output:
    for name, path in [("crop_vertex", "crop.vert.spv"), ("crop_fragment", "crop.frag.spv")]:
        data = directory.joinpath(path).read_bytes()
        words = struct.unpack(f"<{len(data) // 4}I", data)
        print(f"static const uint32_t {name}[] = {{", file=output)
        for index in range(0, len(words), 8):
            print("    " + ", ".join(f"0x{word:08x}" for word in words[index:index + 8]) + ",", file=output)
        print("};", file=output)
PY
cc -std=gnu11 -O2 -Wall -Wextra -Werror -shared -fPIC -fvisibility=hidden \
   -Wl,-z,defs -I "$out" layer.c unix_bridge.c gpu.c composite.c \
   -o "$out/libfelixwgc.so" -lvulkan -pthread
cat > "$out/VkLayer_felix_wgc.json" <<'MANIFEST'
{
    "file_format_version": "1.2.0",
    "layer": {
        "name": "VK_LAYER_FELIX_wgc_dmabuf",
        "type": "GLOBAL",
        "library_path": "./libfelixwgc.so",
        "api_version": "1.3.0",
        "implementation_version": "1",
        "description": "Felix isolated WGC DMA-BUF bridge"
    }
}
MANIFEST
