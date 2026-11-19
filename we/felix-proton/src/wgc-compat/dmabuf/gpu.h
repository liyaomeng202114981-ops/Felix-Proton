// SPDX-License-Identifier: BSD-3-Clause
// Copyright 2026 Felix Li, with OpenAI Codex assistance.
#pragma once
#include "protocol.h"
#include <vulkan/vulkan.h>

#define DRM_MODIFIER_LIMIT 64

struct gpu {
    VkInstance instance;
    VkPhysicalDevice physical;
    VkDevice device;
    VkQueue queue;
    uint32_t family;
    VkCommandPool pool;
    VkCommandBuffer command;
    VkFence fence;
    VkQueryPool timestamps;
    float timestamp_period;
    uint32_t timestamp_bits;
    VkPhysicalDeviceMemoryProperties memory;
    PFN_vkGetMemoryFdPropertiesKHR get_fd_properties;
    uint64_t modifiers[DRM_MODIFIER_LIMIT];
    uint32_t modifier_count;
};

int gpu_init(struct gpu *gpu, const char *render_node);
void gpu_finish(struct gpu *gpu);
int gpu_import(const struct gpu *gpu, int fd, const struct window_buffer *frame,
               VkImage *image, VkDeviceMemory *memory);
int gpu_acquire(int fd);
int gpu_sample(struct gpu *gpu, int fd, const struct window_buffer *frame,
               uint32_t pixels[3]);
