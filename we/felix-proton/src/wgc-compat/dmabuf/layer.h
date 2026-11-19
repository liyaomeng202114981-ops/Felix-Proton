// SPDX-License-Identifier: BSD-3-Clause
// Copyright 2026 Felix Li, with OpenAI Codex assistance.
#pragma once
#include <stdbool.h>
#include <vulkan/vulkan.h>

struct felix_device {
    VkDevice handle;
    VkPhysicalDeviceDrmPropertiesEXT drm;
    VkPhysicalDeviceMemoryProperties memory;
    PFN_vkGetDeviceProcAddr next;
    float timestamp_period;
    uint32_t timestamp_bits[32];
};

bool felix_image_device(VkImage image, struct felix_device *handle);
