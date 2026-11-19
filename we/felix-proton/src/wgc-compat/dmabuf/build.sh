#!/bin/sh
# SPDX-License-Identifier: BSD-3-Clause
set -eu
out="$(realpath -m "$1")"
sysroot=${2:+$(realpath "$2")}
cd "$(dirname "$0")"
if [ -n "$sysroot" ]; then
    inc="$sysroot/usr/include"
    cc -std=gnu11 -O2 -Wall -Wextra -Werror -isystem "$inc/pipewire-0.3" -isystem "$inc/spa-0.2" \
        -isystem "$inc" -isystem "$inc/libdrm" \
        window_stream.c gpu.c relay.c -o "$out" -l:libpipewire-0.3.so.0 -l:libdrm.so.2 -lvulkan
else
    cc -std=gnu11 -O2 -Wall -Wextra -Werror $(pkg-config --cflags libpipewire-0.3 libdrm) \
        window_stream.c gpu.c relay.c -o "$out" $(pkg-config --libs libpipewire-0.3 libdrm vulkan)
fi
