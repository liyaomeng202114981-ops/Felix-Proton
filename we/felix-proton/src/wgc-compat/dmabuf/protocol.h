// SPDX-License-Identifier: BSD-3-Clause
// Copyright 2026 Felix Li, with OpenAI Codex assistance.
#pragma once
#include <stdint.h>

struct window_buffer {
    uint32_t width, height, x, y, crop_width, crop_height;
    uint32_t stride, offset;
    uint64_t modifier;
};

enum { GPU_CONNECT, GPU_NEXT, GPU_COPY, GPU_CLOSE };
enum { WINDOW_REQUEST = 'F', MONITOR_REQUEST = 'M', LEASE_DONE = 'D', LEASE_FAILED = 'X' };
/* In-app window authorizations have distinct source IDs starting here. */
enum { GPU_SOURCE_STATIC, GPU_SOURCE_WINDOW, GPU_SOURCE_MONITOR, GPU_SOURCE_FIRST_WINDOW };
enum { GPU_SOURCE_PENDING = 2 };

struct gpu_timing {
    uint64_t acquire_ns, import_ns, submit_ns, fence_ns, render_ns;
    uint32_t render_measured;
};

struct gpu_call {
    uint64_t context;
    struct window_buffer frame;
    uint64_t image;
    uint32_t layout, family, index, width, height;
    uint32_t trace;
    struct gpu_timing timing;
    uint32_t source;
};

#ifdef __cplusplus
static_assert(sizeof(struct window_buffer) == 40 && sizeof(struct gpu_call) == 136);
#else
_Static_assert(sizeof(struct window_buffer) == 40 && sizeof(struct gpu_call) == 136, "GPU bridge ABI");
#endif
