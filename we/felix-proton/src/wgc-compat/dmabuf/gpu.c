// SPDX-License-Identifier: BSD-3-Clause
// Copyright 2026 Felix Li, with OpenAI Codex assistance.
#define _GNU_SOURCE
#include "gpu.h"

#include <fcntl.h>
#include <linux/dma-buf.h>
#include <poll.h>
#include <stdio.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>

static const VkFormat format = VK_FORMAT_B8G8R8A8_UNORM;
static const VkImageUsageFlags input_usage = VK_IMAGE_USAGE_TRANSFER_SRC_BIT | VK_IMAGE_USAGE_SAMPLED_BIT;
static const VkImageSubresourceRange image_range = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
static const VkExternalMemoryHandleTypeFlagBits handle_type =
    VK_EXTERNAL_MEMORY_HANDLE_TYPE_DMA_BUF_BIT_EXT;

static VkPhysicalDevice find_device(VkInstance instance, const char *render_node)
{
    struct stat node;
    uint32_t count = 32;
    VkPhysicalDevice devices[32];
    if (stat(render_node, &node) || !S_ISCHR(node.st_mode) ||
        vkEnumeratePhysicalDevices(instance, &count, devices) != VK_SUCCESS)
        return VK_NULL_HANDLE;
    for (uint32_t i = 0; i < count; ++i) {
        VkPhysicalDeviceDrmPropertiesEXT drm = {
            .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DRM_PROPERTIES_EXT,
        };
        VkPhysicalDeviceProperties2 properties = {
            .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2, .pNext = &drm,
        };
        vkGetPhysicalDeviceProperties2(devices[i], &properties);
        if (drm.hasRender && drm.renderMajor == major(node.st_rdev) &&
            drm.renderMinor == minor(node.st_rdev)) {
            printf("VULKAN_DEVICE %s\n", properties.properties.deviceName);
            return devices[i];
        }
    }
    return VK_NULL_HANDLE;
}

static void get_modifiers(struct gpu *gpu)
{
    VkDrmFormatModifierPropertiesEXT mods[DRM_MODIFIER_LIMIT];
    VkDrmFormatModifierPropertiesListEXT list = {
        .sType = VK_STRUCTURE_TYPE_DRM_FORMAT_MODIFIER_PROPERTIES_LIST_EXT,
        .drmFormatModifierCount = DRM_MODIFIER_LIMIT, .pDrmFormatModifierProperties = mods,
    };
    VkFormatProperties2 properties = {
        .sType = VK_STRUCTURE_TYPE_FORMAT_PROPERTIES_2, .pNext = &list,
    };
    vkGetPhysicalDeviceFormatProperties2(gpu->physical, format, &properties);
    for (uint32_t i = 0; i < list.drmFormatModifierCount && i < DRM_MODIFIER_LIMIT; ++i) {
        if (mods[i].drmFormatModifierPlaneCount != 1 ||
            (mods[i].drmFormatModifierTilingFeatures & (VK_FORMAT_FEATURE_TRANSFER_SRC_BIT | VK_FORMAT_FEATURE_SAMPLED_IMAGE_BIT)) !=
            (VK_FORMAT_FEATURE_TRANSFER_SRC_BIT | VK_FORMAT_FEATURE_SAMPLED_IMAGE_BIT))
            continue;
        const VkPhysicalDeviceExternalImageFormatInfo external = {
            .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_EXTERNAL_IMAGE_FORMAT_INFO,
            .handleType = handle_type,
        };
        const VkPhysicalDeviceImageDrmFormatModifierInfoEXT modifier = {
            .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_IMAGE_DRM_FORMAT_MODIFIER_INFO_EXT,
            .pNext = &external, .drmFormatModifier = mods[i].drmFormatModifier,
            .sharingMode = VK_SHARING_MODE_EXCLUSIVE,
        };
        const VkPhysicalDeviceImageFormatInfo2 image = {
            .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_IMAGE_FORMAT_INFO_2, .pNext = &modifier,
            .format = format, .type = VK_IMAGE_TYPE_2D, .tiling = VK_IMAGE_TILING_DRM_FORMAT_MODIFIER_EXT,
            .usage = input_usage,
        };
        VkExternalImageFormatProperties import = {
            .sType = VK_STRUCTURE_TYPE_EXTERNAL_IMAGE_FORMAT_PROPERTIES,
        };
        VkImageFormatProperties2 supported = {
            .sType = VK_STRUCTURE_TYPE_IMAGE_FORMAT_PROPERTIES_2, .pNext = &import,
        };
        if (vkGetPhysicalDeviceImageFormatProperties2(gpu->physical, &image, &supported) == VK_SUCCESS &&
            (import.externalMemoryProperties.externalMemoryFeatures & VK_EXTERNAL_MEMORY_FEATURE_IMPORTABLE_BIT))
            gpu->modifiers[gpu->modifier_count++] = modifier.drmFormatModifier;
    }
}

int gpu_init(struct gpu *gpu, const char *render_node)
{
    const char *extensions[] = {VK_EXT_EXTERNAL_MEMORY_DMA_BUF_EXTENSION_NAME,
        VK_KHR_EXTERNAL_MEMORY_FD_EXTENSION_NAME, VK_EXT_IMAGE_DRM_FORMAT_MODIFIER_EXTENSION_NAME,
        VK_EXT_QUEUE_FAMILY_FOREIGN_EXTENSION_NAME};
    const VkApplicationInfo app = {.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO,
        .pApplicationName = "Felix WGC Wayland import probe", .apiVersion = VK_API_VERSION_1_2};
    const VkInstanceCreateInfo instance = {.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,
        .pApplicationInfo = &app};
    if (vkCreateInstance(&instance, NULL, &gpu->instance) != VK_SUCCESS ||
        !(gpu->physical = find_device(gpu->instance, render_node)))
        return -1;
    get_modifiers(gpu);
    if (!gpu->modifier_count)
        return -1;
    uint32_t count = 32;
    VkQueueFamilyProperties families[32];
    vkGetPhysicalDeviceQueueFamilyProperties(gpu->physical, &count, families);
    while (gpu->family < count && !(families[gpu->family].queueFlags & VK_QUEUE_GRAPHICS_BIT))
        ++gpu->family;
    if (gpu->family == count)
        return -1;
    const float priority = 1;
    const VkDeviceQueueCreateInfo queue = {.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
        .queueFamilyIndex = gpu->family, .queueCount = 1, .pQueuePriorities = &priority};
    const VkDeviceCreateInfo device = {.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
        .queueCreateInfoCount = 1, .pQueueCreateInfos = &queue,
        .enabledExtensionCount = sizeof(extensions) / sizeof(extensions[0]),
        .ppEnabledExtensionNames = extensions};
    if (vkCreateDevice(gpu->physical, &device, NULL, &gpu->device) != VK_SUCCESS)
        return -1;
    vkGetDeviceQueue(gpu->device, gpu->family, 0, &gpu->queue);
    vkGetPhysicalDeviceMemoryProperties(gpu->physical, &gpu->memory);
    gpu->get_fd_properties = (PFN_vkGetMemoryFdPropertiesKHR)
        vkGetDeviceProcAddr(gpu->device, "vkGetMemoryFdPropertiesKHR");
    const VkCommandPoolCreateInfo pool = {.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,
        .queueFamilyIndex = gpu->family, .flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT};
    if (!gpu->get_fd_properties || vkCreateCommandPool(gpu->device, &pool, NULL, &gpu->pool) != VK_SUCCESS)
        return -1;
    const VkCommandBufferAllocateInfo command = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
        .commandPool = gpu->pool, .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY, .commandBufferCount = 1};
    const VkFenceCreateInfo fence = {.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
    if (vkAllocateCommandBuffers(gpu->device, &command, &gpu->command) != VK_SUCCESS ||
        vkCreateFence(gpu->device, &fence, NULL, &gpu->fence) != VK_SUCCESS)
        return -1;
    return 0;
}

void gpu_finish(struct gpu *gpu)
{
    if (gpu->device) {
        vkDeviceWaitIdle(gpu->device);
        vkDestroyFence(gpu->device, gpu->fence, NULL);
        vkDestroyCommandPool(gpu->device, gpu->pool, NULL);
        vkDestroyDevice(gpu->device, NULL);
    }
    if (gpu->instance)
        vkDestroyInstance(gpu->instance, NULL);
}

static uint32_t memory_type(const struct gpu *gpu, uint32_t mask, VkMemoryPropertyFlags flags)
{
    for (uint32_t i = 0; i < gpu->memory.memoryTypeCount; ++i)
        if ((mask & (1u << i)) &&
            (gpu->memory.memoryTypes[i].propertyFlags & flags) == flags)
            return i;
    return UINT32_MAX;
}

int gpu_import(const struct gpu *gpu, int fd, const struct window_buffer *frame,
               VkImage *image, VkDeviceMemory *memory)
{
    const VkExternalMemoryImageCreateInfo external = {
        .sType = VK_STRUCTURE_TYPE_EXTERNAL_MEMORY_IMAGE_CREATE_INFO, .handleTypes = handle_type,
    };
    const VkSubresourceLayout plane = {.offset = frame->offset, .rowPitch = frame->stride};
    const VkImageDrmFormatModifierExplicitCreateInfoEXT modifier = {
        .sType = VK_STRUCTURE_TYPE_IMAGE_DRM_FORMAT_MODIFIER_EXPLICIT_CREATE_INFO_EXT,
        .pNext = &external, .drmFormatModifier = frame->modifier,
        .drmFormatModifierPlaneCount = 1, .pPlaneLayouts = &plane,
    };
    const VkImageCreateInfo desc = {
        .sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO, .pNext = &modifier,
        .imageType = VK_IMAGE_TYPE_2D, .format = format, .extent = {frame->width, frame->height, 1},
        .mipLevels = 1, .arrayLayers = 1, .samples = VK_SAMPLE_COUNT_1_BIT,
        .tiling = VK_IMAGE_TILING_DRM_FORMAT_MODIFIER_EXT, .usage = input_usage,
        .sharingMode = VK_SHARING_MODE_EXCLUSIVE, .initialLayout = VK_IMAGE_LAYOUT_UNDEFINED,
    };
    VkResult result = vkCreateImage(gpu->device, &desc, NULL, image);
    if (result != VK_SUCCESS)
        return result;
    VkMemoryRequirements requirement;
    vkGetImageMemoryRequirements(gpu->device, *image, &requirement);
    VkMemoryFdPropertiesKHR properties = {.sType = VK_STRUCTURE_TYPE_MEMORY_FD_PROPERTIES_KHR};
    result = gpu->get_fd_properties(gpu->device, handle_type, fd, &properties);
    if (result != VK_SUCCESS)
        return result;
    uint32_t index = memory_type(gpu, requirement.memoryTypeBits & properties.memoryTypeBits, 0);
    if (index == UINT32_MAX)
        return VK_ERROR_INCOMPATIBLE_DRIVER;
    int fd_copy = fcntl(fd, F_DUPFD_CLOEXEC, 3);
    if (fd_copy == -1)
        return VK_ERROR_INVALID_EXTERNAL_HANDLE;
    const VkMemoryDedicatedAllocateInfo dedicated = {
        .sType = VK_STRUCTURE_TYPE_MEMORY_DEDICATED_ALLOCATE_INFO, .image = *image,
    };
    const VkImportMemoryFdInfoKHR import = {
        .sType = VK_STRUCTURE_TYPE_IMPORT_MEMORY_FD_INFO_KHR, .pNext = &dedicated,
        .handleType = handle_type, .fd = fd_copy,
    };
    const VkMemoryAllocateInfo allocation = {
        .sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, .pNext = &import,
        .allocationSize = requirement.size, .memoryTypeIndex = index,
    };
    result = vkAllocateMemory(gpu->device, &allocation, NULL, memory);
    if (result != VK_SUCCESS) {
        close(fd_copy);
        return result;
    }
    return vkBindImageMemory(gpu->device, *image, *memory, 0);
}

int gpu_acquire(int fd)
{
    struct dma_buf_export_sync_file sync = {.flags = DMA_BUF_SYNC_READ, .fd = -1};
    if (ioctl(fd, DMA_BUF_IOCTL_EXPORT_SYNC_FILE, &sync) < 0)
        return -1;
    struct pollfd ready = {.fd = sync.fd, .events = POLLIN};
    const int n = poll(&ready, 1, 1500);
    close(sync.fd);
    return n == 1 && (ready.revents & POLLIN) ? 0 : -1;
}

int gpu_sample(struct gpu *gpu, int fd, const struct window_buffer *frame, uint32_t pixels[3])
{
    VkImage image = VK_NULL_HANDLE;
    VkDeviceMemory imported = VK_NULL_HANDLE, staging = VK_NULL_HANDLE;
    VkBuffer buffer = VK_NULL_HANDLE;
    VkMemoryRequirements requirements;
    int result = gpu_acquire(fd);
    if (result) return result;
    result = gpu_import(gpu, fd, frame, &image, &imported);
    if (result) goto done;

    const VkBufferCreateInfo target = {.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO,
        .size = 12, .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT, .sharingMode = VK_SHARING_MODE_EXCLUSIVE};
    if ((result = vkCreateBuffer(gpu->device, &target, NULL, &buffer))) goto done;
    vkGetBufferMemoryRequirements(gpu->device, buffer, &requirements);
    const VkMemoryAllocateInfo allocation = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO,
        .allocationSize = requirements.size,
        .memoryTypeIndex = memory_type(gpu, requirements.memoryTypeBits,
                                      VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)};
    if (allocation.memoryTypeIndex == UINT32_MAX) {
        result = VK_ERROR_MEMORY_MAP_FAILED;
        goto done;
    }
    if ((result = vkAllocateMemory(gpu->device, &allocation, NULL, &staging)) ||
        (result = vkBindBufferMemory(gpu->device, buffer, staging, 0))) goto done;

    const VkCommandBufferBeginInfo begin = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO,
        .flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT};
    if ((result = vkResetCommandBuffer(gpu->command, 0)) ||
        (result = vkBeginCommandBuffer(gpu->command, &begin))) goto done;
    VkImageMemoryBarrier ownership = {.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
        .dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT, .oldLayout = VK_IMAGE_LAYOUT_GENERAL,
        .newLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
        .srcQueueFamilyIndex = VK_QUEUE_FAMILY_FOREIGN_EXT, .dstQueueFamilyIndex = gpu->family,
        .image = image, .subresourceRange = image_range};
    vkCmdPipelineBarrier(gpu->command, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT,
                         0, 0, NULL, 0, NULL, 1, &ownership);
    VkBufferImageCopy points[3];
    for (unsigned i = 0; i < 3; ++i) {
        points[i] = (VkBufferImageCopy){
            .bufferOffset = i * 4, .imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1},
            .imageOffset = {frame->x + frame->crop_width * (i ? 3 : 1) / 4,
                            frame->y + frame->crop_height * (i == 2 ? 3 : 1) / 4, 0},
            .imageExtent = {1, 1, 1},
        };
    }
    vkCmdCopyImageToBuffer(gpu->command, image, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, buffer, 3, points);
    ownership.srcAccessMask = VK_ACCESS_TRANSFER_READ_BIT;
    ownership.dstAccessMask = 0;
    ownership.oldLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL;
    ownership.newLayout = VK_IMAGE_LAYOUT_GENERAL;
    ownership.srcQueueFamilyIndex = gpu->family;
    ownership.dstQueueFamilyIndex = VK_QUEUE_FAMILY_FOREIGN_EXT;
    vkCmdPipelineBarrier(gpu->command, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT,
                         0, 0, NULL, 0, NULL, 1, &ownership);
    if ((result = vkEndCommandBuffer(gpu->command)) ||
        (result = vkResetFences(gpu->device, 1, &gpu->fence))) goto done;
    const VkSubmitInfo submit = {.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO,
        .commandBufferCount = 1, .pCommandBuffers = &gpu->command};
    if ((result = vkQueueSubmit(gpu->queue, 1, &submit, gpu->fence)) ||
        (result = vkWaitForFences(gpu->device, 1, &gpu->fence, VK_TRUE, UINT64_MAX))) goto done;
    void *mapping;
    result = vkMapMemory(gpu->device, staging, 0, 12, 0, &mapping);
    if (!result) {
        const uint32_t *values = mapping;
        for (unsigned i = 0; i < 3; ++i) pixels[i] = values[i] & 0xffffff;
        vkUnmapMemory(gpu->device, staging);
    }
done:
    vkDestroyBuffer(gpu->device, buffer, NULL);
    vkFreeMemory(gpu->device, staging, NULL);
    vkDestroyImage(gpu->device, image, NULL);
    vkFreeMemory(gpu->device, imported, NULL);
    return result;
}
