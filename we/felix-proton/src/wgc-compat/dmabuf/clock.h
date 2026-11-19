// SPDX-License-Identifier: BSD-3-Clause
// Copyright 2026 Felix Li, with OpenAI Codex assistance.
#pragma once

#include <stdint.h>
#include <time.h>

static inline uint64_t monotonic_ns(void)
{
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return (uint64_t)now.tv_sec * 1000000000ull + now.tv_nsec;
}
