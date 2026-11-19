// SPDX-License-Identifier: BSD-3-Clause
// Copyright 2026 Felix Li, with OpenAI Codex assistance.
#pragma once
#include "gpu.h"

struct composite {
    VkRenderPass render;
    VkPipeline pipeline;
    VkDescriptorSetLayout descriptors;
    VkDescriptorPool descriptor_pool;
    VkDescriptorSet descriptor;
    VkPipelineLayout layout;
    VkSampler sampler;
};

int composite_init(struct composite *state, VkDevice device);
void composite_finish(struct composite *state, VkDevice device);
int composite_crop(struct composite *state, struct gpu *gpu, VkImage input, struct gpu_call *args);
