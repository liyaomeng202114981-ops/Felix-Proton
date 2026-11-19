// SPDX-License-Identifier: BSD-3-Clause
// Copyright 2026 Felix Li, with OpenAI Codex assistance.
#pragma once
#include "protocol.h"

int relay_open(const char *path);
int relay_frame(int listening, int *client, int frame_fd, char source_request, const struct window_buffer *frame);
