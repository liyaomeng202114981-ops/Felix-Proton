// SPDX-License-Identifier: BSD-3-Clause
// Copyright 2026 Felix Li, with OpenAI Codex assistance.
#include "composite.h"
#include "clock.h"
#include "shaders.h"
#include <stdbool.h>

static const VkFormat format = VK_FORMAT_B8G8R8A8_UNORM;
static const VkImageSubresourceRange range = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};

static VkResult render_pass(struct composite *state, VkDevice device)
{
    const VkAttachmentDescription color = {
        .format=format, .samples=VK_SAMPLE_COUNT_1_BIT,
        .loadOp=VK_ATTACHMENT_LOAD_OP_CLEAR, .storeOp=VK_ATTACHMENT_STORE_OP_STORE,
        .stencilLoadOp=VK_ATTACHMENT_LOAD_OP_DONT_CARE, .stencilStoreOp=VK_ATTACHMENT_STORE_OP_DONT_CARE,
        .initialLayout=VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL,
        .finalLayout=VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL,
    };
    const VkAttachmentReference output = {0, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL};
    const VkSubpassDescription subpass = {
        .pipelineBindPoint=VK_PIPELINE_BIND_POINT_GRAPHICS, .colorAttachmentCount=1, .pColorAttachments=&output,
    };
    const VkRenderPassCreateInfo passes = {.sType=VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO,
        .attachmentCount=1, .pAttachments=&color, .subpassCount=1, .pSubpasses=&subpass};
    return vkCreateRenderPass(device, &passes, NULL, &state->render);
}

static VkResult graphics_pipeline(struct composite *state, VkDevice device)
{
    VkShaderModule vertex = VK_NULL_HANDLE, fragment = VK_NULL_HANDLE;
    VkShaderModuleCreateInfo shader = {.sType=VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO,
        .codeSize=sizeof(crop_vertex), .pCode=crop_vertex};
    VkResult result = vkCreateShaderModule(device, &shader, NULL, &vertex);
    if (result) goto done;
    shader.codeSize = sizeof(crop_fragment);
    shader.pCode = crop_fragment;
    if ((result = vkCreateShaderModule(device, &shader, NULL, &fragment))) goto done;
    const VkPipelineShaderStageCreateInfo stages[] = {
        {.sType=VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,
         .stage=VK_SHADER_STAGE_VERTEX_BIT, .module=vertex, .pName="main"},
        {.sType=VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO,
         .stage=VK_SHADER_STAGE_FRAGMENT_BIT, .module=fragment, .pName="main"},
    };
    const VkPipelineVertexInputStateCreateInfo vertices = {
        .sType=VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO,
    };
    const VkPipelineInputAssemblyStateCreateInfo assembly = {
        .sType=VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO,
        .topology=VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST,
    };
    const VkPipelineViewportStateCreateInfo viewport = {
        .sType=VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO, .viewportCount=1, .scissorCount=1,
    };
    const VkPipelineRasterizationStateCreateInfo raster = {
        .sType=VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO,
        .polygonMode=VK_POLYGON_MODE_FILL, .lineWidth=1,
    };
    const VkPipelineMultisampleStateCreateInfo samples = {
        .sType=VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO,
        .rasterizationSamples=VK_SAMPLE_COUNT_1_BIT,
    };
    const VkPipelineColorBlendAttachmentState components = {
        .colorWriteMask=VK_COLOR_COMPONENT_R_BIT|VK_COLOR_COMPONENT_G_BIT|
                        VK_COLOR_COMPONENT_B_BIT|VK_COLOR_COMPONENT_A_BIT,
    };
    const VkPipelineColorBlendStateCreateInfo colors = {
        .sType=VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO,
        .attachmentCount=1, .pAttachments=&components,
    };
    const VkDynamicState states[] = {VK_DYNAMIC_STATE_VIEWPORT, VK_DYNAMIC_STATE_SCISSOR};
    const VkPipelineDynamicStateCreateInfo dynamic = {.sType=VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO,
        .dynamicStateCount=2, .pDynamicStates=states};
    const VkGraphicsPipelineCreateInfo info = {.sType=VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO,
        .stageCount=2, .pStages=stages, .pVertexInputState=&vertices, .pInputAssemblyState=&assembly,
        .pViewportState=&viewport, .pRasterizationState=&raster, .pMultisampleState=&samples,
        .pColorBlendState=&colors, .pDynamicState=&dynamic, .renderPass=state->render, .layout=state->layout};
    result = vkCreateGraphicsPipelines(device, VK_NULL_HANDLE, 1, &info, NULL, &state->pipeline);
done:
    vkDestroyShaderModule(device, fragment, NULL);
    vkDestroyShaderModule(device, vertex, NULL);
    return result;
}

int composite_init(struct composite *state, VkDevice device)
{
    VkResult result = render_pass(state, device);
    if (result) return result;
    const VkSamplerCreateInfo sampler = {.sType=VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO,
        .magFilter=VK_FILTER_NEAREST, .minFilter=VK_FILTER_NEAREST,
        .addressModeU=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,
        .addressModeV=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE,
        .addressModeW=VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE};
    if ((result = vkCreateSampler(device, &sampler, NULL, &state->sampler))) return result;
    const VkDescriptorSetLayoutBinding binding = {
        .descriptorType=VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,
        .descriptorCount=1, .stageFlags=VK_SHADER_STAGE_FRAGMENT_BIT, .pImmutableSamplers=&state->sampler,
    };
    const VkDescriptorSetLayoutCreateInfo descriptors = {
        .sType=VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO, .bindingCount=1, .pBindings=&binding,
    };
    if ((result = vkCreateDescriptorSetLayout(device, &descriptors, NULL, &state->descriptors))) return result;
    const VkPushConstantRange offset = {.stageFlags=VK_SHADER_STAGE_FRAGMENT_BIT, .size=8};
    const VkPipelineLayoutCreateInfo layout = {.sType=VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO,
        .setLayoutCount=1, .pSetLayouts=&state->descriptors, .pushConstantRangeCount=1, .pPushConstantRanges=&offset};
    if ((result = vkCreatePipelineLayout(device, &layout, NULL, &state->layout))) return result;
    const VkDescriptorPoolSize pool_size = {VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 1};
    const VkDescriptorPoolCreateInfo pool = {.sType=VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO,
        .maxSets=1, .poolSizeCount=1, .pPoolSizes=&pool_size};
    if ((result = vkCreateDescriptorPool(device, &pool, NULL, &state->descriptor_pool))) return result;
    const VkDescriptorSetAllocateInfo allocate = {.sType=VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO,
        .descriptorPool=state->descriptor_pool, .descriptorSetCount=1, .pSetLayouts=&state->descriptors};
    if ((result = vkAllocateDescriptorSets(device, &allocate, &state->descriptor))) return result;
    return graphics_pipeline(state, device);
}

void composite_finish(struct composite *state, VkDevice device)
{
    vkDestroyPipeline(device, state->pipeline, NULL);
    vkDestroyPipelineLayout(device, state->layout, NULL);
    vkDestroyDescriptorPool(device, state->descriptor_pool, NULL);
    vkDestroyDescriptorSetLayout(device, state->descriptors, NULL);
    vkDestroySampler(device, state->sampler, NULL);
    vkDestroyRenderPass(device, state->render, NULL);
}

static void layout_barriers(const struct gpu *gpu, VkImage input, VkImage target,
                            VkImageLayout initial, bool entering)
{
    const VkImageMemoryBarrier barriers[] = {
        {.sType=VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
         .srcAccessMask=entering ? 0 : VK_ACCESS_SHADER_READ_BIT,
         .dstAccessMask=entering ? VK_ACCESS_SHADER_READ_BIT : 0,
         .oldLayout=entering ? VK_IMAGE_LAYOUT_GENERAL : VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL,
         .newLayout=entering ? VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL : VK_IMAGE_LAYOUT_GENERAL,
         .srcQueueFamilyIndex=entering ? VK_QUEUE_FAMILY_FOREIGN_EXT : gpu->family,
         .dstQueueFamilyIndex=entering ? gpu->family : VK_QUEUE_FAMILY_FOREIGN_EXT,
         .image=input, .subresourceRange=range},
        {.sType=VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
         .srcAccessMask=entering ? VK_ACCESS_MEMORY_READ_BIT|VK_ACCESS_MEMORY_WRITE_BIT : VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT,
         .dstAccessMask=entering ? VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT : VK_ACCESS_MEMORY_READ_BIT|VK_ACCESS_MEMORY_WRITE_BIT,
         .oldLayout=entering ? initial : VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL,
         .newLayout=entering ? VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL : initial,
         .srcQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED, .dstQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED,
         .image=target, .subresourceRange=range},
    };
    const VkPipelineStageFlags render = VK_PIPELINE_STAGE_FRAGMENT_SHADER_BIT|VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;
    vkCmdPipelineBarrier(gpu->command, entering ? VK_PIPELINE_STAGE_ALL_COMMANDS_BIT : render,
                         entering ? render : VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,
                         0, 0, NULL, 0, NULL, 2, barriers);
}

int composite_crop(struct composite *state, struct gpu *gpu, VkImage input, struct gpu_call *args)
{
    VkResult result;
    VkImageView source = VK_NULL_HANDLE, output = VK_NULL_HANDLE;
    VkFramebuffer framebuffer = VK_NULL_HANDLE;
    const VkImage target = (VkImage)(uintptr_t)args->image;
    VkImageViewCreateInfo view = {.sType=VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO,
        .image=input, .viewType=VK_IMAGE_VIEW_TYPE_2D, .format=format, .subresourceRange=range};
    if ((result = vkCreateImageView(gpu->device, &view, NULL, &source))) goto done;
    view.image = target;
    if ((result = vkCreateImageView(gpu->device, &view, NULL, &output))) goto done;
    const VkFramebufferCreateInfo fb = {.sType=VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO,
        .renderPass=state->render, .attachmentCount=1, .pAttachments=&output,
        .width=args->width, .height=args->height, .layers=1};
    if ((result = vkCreateFramebuffer(gpu->device, &fb, NULL, &framebuffer))) goto done;

    const VkDescriptorImageInfo source_image = {.imageView=source, .imageLayout=VK_IMAGE_LAYOUT_SHADER_READ_ONLY_OPTIMAL};
    const VkWriteDescriptorSet write = {.sType=VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET,
        .dstSet=state->descriptor, .descriptorCount=1, .descriptorType=VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER,
        .pImageInfo=&source_image};
    vkUpdateDescriptorSets(gpu->device, 1, &write, 0, NULL);
    const VkCommandBufferBeginInfo begin = {.sType=VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO,
        .flags=VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT};
    if ((result = vkResetCommandBuffer(gpu->command, 0)) ||
        (result = vkBeginCommandBuffer(gpu->command, &begin))) goto done;
    if (gpu->timestamps) {
        vkCmdResetQueryPool(gpu->command, gpu->timestamps, 0, 2);
        vkCmdWriteTimestamp(gpu->command, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, gpu->timestamps, 0);
    }
    layout_barriers(gpu, input, target, args->layout, true);
    const VkClearValue background = {.color={.float32={0, 0, 0, 1}}};
    const VkRenderPassBeginInfo pass = {.sType=VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO,
        .renderPass=state->render, .framebuffer=framebuffer, .renderArea={{0,0},{args->width,args->height}},
        .clearValueCount=1, .pClearValues=&background};
    const uint32_t width = args->frame.crop_width < args->width ? args->frame.crop_width : args->width;
    const uint32_t height = args->frame.crop_height < args->height ? args->frame.crop_height : args->height;
    const VkViewport viewport = {0, 0, width, height, 0, 1};
    const VkRect2D scissor = {{0,0},{width,height}};
    const int32_t offset[2] = {(int32_t)args->frame.x, (int32_t)args->frame.y};
    vkCmdBeginRenderPass(gpu->command, &pass, VK_SUBPASS_CONTENTS_INLINE);
    vkCmdSetViewport(gpu->command, 0, 1, &viewport);
    vkCmdSetScissor(gpu->command, 0, 1, &scissor);
    vkCmdBindPipeline(gpu->command, VK_PIPELINE_BIND_POINT_GRAPHICS, state->pipeline);
    vkCmdBindDescriptorSets(gpu->command, VK_PIPELINE_BIND_POINT_GRAPHICS, state->layout,
                            0, 1, &state->descriptor, 0, NULL);
    vkCmdPushConstants(gpu->command, state->layout, VK_SHADER_STAGE_FRAGMENT_BIT, 0, sizeof(offset), offset);
    vkCmdDraw(gpu->command, 3, 1, 0, 0);
    vkCmdEndRenderPass(gpu->command);
    layout_barriers(gpu, input, target, args->layout, false);
    if (gpu->timestamps)
        vkCmdWriteTimestamp(gpu->command, VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT, gpu->timestamps, 1);
    if ((result = vkEndCommandBuffer(gpu->command)) ||
        (result = vkResetFences(gpu->device, 1, &gpu->fence))) goto done;
    const VkSubmitInfo submit = {.sType=VK_STRUCTURE_TYPE_SUBMIT_INFO,
        .commandBufferCount=1, .pCommandBuffers=&gpu->command};
    const uint64_t submitting = args->trace ? monotonic_ns() : 0;
    result = vkQueueSubmit(gpu->queue, 1, &submit, gpu->fence);
    if (!result) {
        const uint64_t waiting = args->trace ? monotonic_ns() : 0;
        result = vkWaitForFences(gpu->device, 1, &gpu->fence, VK_TRUE, UINT64_MAX);
        if (args->trace) {
            args->timing.submit_ns = waiting - submitting;
            args->timing.fence_ns = monotonic_ns() - waiting;
        }
        uint64_t values[2];
        if (!result && gpu->timestamps &&
            vkGetQueryPoolResults(gpu->device, gpu->timestamps, 0, 2, sizeof(values),
                                  values, sizeof(values[0]), VK_QUERY_RESULT_64_BIT) == VK_SUCCESS) {
            const uint64_t mask = UINT64_MAX >> (64 - gpu->timestamp_bits);
            args->timing.render_ns = (uint64_t)(((values[1] - values[0]) & mask) *
                                                  (double)gpu->timestamp_period);
            args->timing.render_measured = 1;
        }
    }
done:
    vkDestroyFramebuffer(gpu->device, framebuffer, NULL);
    vkDestroyImageView(gpu->device, output, NULL);
    vkDestroyImageView(gpu->device, source, NULL);
    return result;
}
