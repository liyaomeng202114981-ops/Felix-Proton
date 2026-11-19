// SPDX-License-Identifier: BSD-3-Clause
// Copyright 2026 Felix Li, with OpenAI Codex assistance.
#include "layer.h"
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <vulkan/vk_layer.h>

typedef struct instance_info {
    VkInstance handle;
    PFN_vkGetInstanceProcAddr next;
    PFN_GetPhysicalDeviceProcAddr next_physical;
    struct instance_info *link;
} instance_info;

typedef struct device_info {
    VkDevice handle;
    PFN_vkGetDeviceProcAddr next;
    VkPhysicalDeviceDrmPropertiesEXT drm;
    VkPhysicalDeviceMemoryProperties memory;
    float timestamp_period;
    uint32_t timestamp_bits[32];
    bool importable;
    struct device_info *link;
} device_info;

typedef struct image_info {
    VkImage handle;
    VkDevice device;
    struct image_info *link;
} image_info;

static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static instance_info *instances;
static device_info *devices;
static image_info *images;

static void *dispatch(const void *handle)
{
    return handle ? *((void *const *)handle) : NULL;
}

static instance_info find_instance(const void *handle)
{
    instance_info copy = {0};
    pthread_mutex_lock(&mutex);
    for (const instance_info *i = instances; i; i = i->link)
        if (dispatch(handle) == dispatch(i->handle)) { copy = *i; break; }
    pthread_mutex_unlock(&mutex);
    return copy;
}

static device_info find_device(VkDevice handle)
{
    device_info copy = {0};
    pthread_mutex_lock(&mutex);
    for (const device_info *i = devices; i; i = i->link)
        if (handle == i->handle) { copy = *i; break; }
    pthread_mutex_unlock(&mutex);
    return copy;
}

bool felix_image_device(VkImage image, struct felix_device *handle)
{
    bool found = false;
    pthread_mutex_lock(&mutex);
    for (const image_info *i = images; i && !found; i = i->link) {
        if (i->handle != image) continue;
        for (const device_info *d = devices; d; d = d->link)
            if (d->handle == i->device && d->importable) {
                *handle = (struct felix_device){
                    .handle=d->handle, .drm=d->drm, .memory=d->memory, .next=d->next,
                    .timestamp_period=d->timestamp_period,
                };
                memcpy(handle->timestamp_bits, d->timestamp_bits, sizeof(handle->timestamp_bits));
                found = true;
                break;
            }
    }
    pthread_mutex_unlock(&mutex);
    return found;
}

static VKAPI_ATTR VkResult VKAPI_CALL create_instance(const VkInstanceCreateInfo *info,
    const VkAllocationCallbacks *allocator, VkInstance *instance)
{
    const VkBaseInStructure *next = info->pNext;
    while (next && (next->sType != VK_STRUCTURE_TYPE_LOADER_INSTANCE_CREATE_INFO ||
            ((const VkLayerInstanceCreateInfo *)next)->function != VK_LAYER_LINK_INFO)) next = next->pNext;
    if (!next) return VK_ERROR_INITIALIZATION_FAILED;

    VkLayerInstanceCreateInfo *chain = (VkLayerInstanceCreateInfo *)next;
    VkLayerInstanceLink *link = chain->u.pLayerInfo;
    instance_info *state = calloc(1, sizeof(*state));
    if (!state) return VK_ERROR_OUT_OF_HOST_MEMORY;
    state->next = link->pfnNextGetInstanceProcAddr;
    state->next_physical = link->pfnNextGetPhysicalDeviceProcAddr;
    const PFN_vkCreateInstance create = (PFN_vkCreateInstance)state->next(NULL, "vkCreateInstance");
    chain->u.pLayerInfo = link->pNext;
    const VkResult result = create ? create(info, allocator, instance) : VK_ERROR_INITIALIZATION_FAILED;
    if (result != VK_SUCCESS) { free(state); return result; }
    state->handle = *instance;
    pthread_mutex_lock(&mutex);
    state->link = instances;
    instances = state;
    pthread_mutex_unlock(&mutex);
    return result;
}

static VKAPI_ATTR void VKAPI_CALL destroy_instance(VkInstance instance, const VkAllocationCallbacks *allocator)
{
    const instance_info state = find_instance(instance);
    pthread_mutex_lock(&mutex);
    for (instance_info **i = &instances; *i; i = &(*i)->link) {
        instance_info *entry = *i;
        if (entry->handle != instance) continue;
        *i = entry->link;
        free(entry);
        break;
    }
    pthread_mutex_unlock(&mutex);
    ((PFN_vkDestroyInstance)state.next(instance, "vkDestroyInstance"))(instance, allocator);
}

static const char *extensions[] = {
    VK_KHR_EXTERNAL_MEMORY_FD_EXTENSION_NAME,
    VK_EXT_EXTERNAL_MEMORY_DMA_BUF_EXTENSION_NAME,
    VK_EXT_IMAGE_DRM_FORMAT_MODIFIER_EXTENSION_NAME,
    VK_EXT_QUEUE_FAMILY_FOREIGN_EXTENSION_NAME,
};
#define EXTENSION_COUNT (sizeof(extensions) / sizeof(extensions[0]))

static bool supported(const instance_info *instance, VkPhysicalDevice physical)
{
    PFN_vkEnumerateDeviceExtensionProperties enumerate = (PFN_vkEnumerateDeviceExtensionProperties)
        instance->next(instance->handle, "vkEnumerateDeviceExtensionProperties");
    uint32_t count = 0;
    if (!enumerate || enumerate(physical, NULL, &count, NULL) != VK_SUCCESS || !count)
        return false;
    VkExtensionProperties *props = calloc(count, sizeof(*props));
    if (!props) return false;
    bool found[EXTENSION_COUNT] = {0}, ok = false;
    if (enumerate(physical, NULL, &count, props) == VK_SUCCESS) {
        for (unsigned n = 0; n < EXTENSION_COUNT; ++n)
            for (unsigned i = 0; i < count; ++i)
                found[n] |= strcmp(props[i].extensionName, extensions[n]) == 0;
        ok = true;
        for (unsigned n = 0; n < EXTENSION_COUNT; ++n) ok &= found[n];
    }
    free(props);
    return ok;
}

static VKAPI_ATTR VkResult VKAPI_CALL create_device(VkPhysicalDevice physical,
    const VkDeviceCreateInfo *info, const VkAllocationCallbacks *allocator, VkDevice *device)
{
    instance_info instance = find_instance(physical);
    if (!instance.handle) return VK_ERROR_INITIALIZATION_FAILED;
    const VkBaseInStructure *next = info->pNext;
    while (next && (next->sType != VK_STRUCTURE_TYPE_LOADER_DEVICE_CREATE_INFO ||
            ((const VkLayerDeviceCreateInfo *)next)->function != VK_LAYER_LINK_INFO)) next = next->pNext;
    if (!next) return VK_ERROR_INITIALIZATION_FAILED;
    VkLayerDeviceCreateInfo *chain = (VkLayerDeviceCreateInfo *)next;
    VkLayerDeviceLink *link = chain->u.pLayerInfo;
    const PFN_vkCreateDevice create = (PFN_vkCreateDevice)
        link->pfnNextGetInstanceProcAddr(instance.handle, "vkCreateDevice");
    device_info *state = calloc(1, sizeof(*state));
    if (!create || !state) { free(state); return VK_ERROR_INITIALIZATION_FAILED; }
    state->next = link->pfnNextGetDeviceProcAddr;
    state->importable = supported(&instance, physical);
    if (state->importable) {
        state->drm.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DRM_PROPERTIES_EXT;
        const PFN_vkGetPhysicalDeviceProperties2 properties =
            (PFN_vkGetPhysicalDeviceProperties2)instance.next(instance.handle, "vkGetPhysicalDeviceProperties2");
        const PFN_vkGetPhysicalDeviceMemoryProperties memory =
            (PFN_vkGetPhysicalDeviceMemoryProperties)instance.next(instance.handle, "vkGetPhysicalDeviceMemoryProperties");
        VkPhysicalDeviceProperties2 props = {.sType=VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2, .pNext=&state->drm};
        if (properties && memory) {
            properties(physical, &props);
            memory(physical, &state->memory);
            state->timestamp_period = props.properties.limits.timestampPeriod;
            const PFN_vkGetPhysicalDeviceQueueFamilyProperties queues =
                (PFN_vkGetPhysicalDeviceQueueFamilyProperties)instance.next(instance.handle,
                    "vkGetPhysicalDeviceQueueFamilyProperties");
            if (queues) {
                VkQueueFamilyProperties properties[32];
                uint32_t count = sizeof(properties) / sizeof(properties[0]);
                queues(physical, &count, properties);
                for (unsigned i = 0; i < count; ++i)
                    state->timestamp_bits[i] = properties[i].timestampValidBits;
            }
        } else state->importable = false;
    }
    chain->u.pLayerInfo = link->pNext;
    VkDeviceCreateInfo enable = *info;
    const char **names = NULL;
    if (state->importable) {
        names = calloc(info->enabledExtensionCount + EXTENSION_COUNT, sizeof(*names));
        if (!names) { free(state); return VK_ERROR_OUT_OF_HOST_MEMORY; }
        for (unsigned n = 0; n < info->enabledExtensionCount; ++n)
            names[n] = info->ppEnabledExtensionNames[n];
        for (unsigned n = 0; n < EXTENSION_COUNT; ++n) {
            bool already = false;
            for (unsigned i = 0; i < info->enabledExtensionCount; ++i)
                already |= strcmp(names[i], extensions[n]) == 0;
            if (!already) names[enable.enabledExtensionCount++] = extensions[n];
        }
        enable.ppEnabledExtensionNames = names;
    }
    const VkResult result = create(physical, &enable, allocator, device);
    free(names);
    if (result != VK_SUCCESS) { free(state); return result; }
    state->handle = *device;
    pthread_mutex_lock(&mutex);
    state->link = devices;
    devices = state;
    pthread_mutex_unlock(&mutex);
    return result;
}

static VKAPI_ATTR void VKAPI_CALL destroy_device(VkDevice device, const VkAllocationCallbacks *allocator)
{
    device_info state = find_device(device);
    pthread_mutex_lock(&mutex);
    for (image_info **i = &images; *i;) {
        image_info *entry = *i;
        if (entry->device != device) { i = &entry->link; continue; }
        *i = entry->link;
        free(entry);
    }
    for (device_info **i = &devices; *i; i = &(*i)->link) {
        device_info *entry = *i;
        if (entry->handle != device) continue;
        *i = entry->link;
        free(entry);
        break;
    }
    pthread_mutex_unlock(&mutex);
    ((PFN_vkDestroyDevice)state.next(device, "vkDestroyDevice"))(device, allocator);
}

static VKAPI_ATTR VkResult VKAPI_CALL create_image(VkDevice device, const VkImageCreateInfo *info,
    const VkAllocationCallbacks *allocator, VkImage *image)
{
    device_info state = find_device(device);
    const PFN_vkCreateImage create = (PFN_vkCreateImage)state.next(device, "vkCreateImage");
    const VkResult result = create(device, info, allocator, image);
    if (result != VK_SUCCESS || !state.importable || info->format != VK_FORMAT_B8G8R8A8_UNORM ||
        info->tiling != VK_IMAGE_TILING_OPTIMAL || !(info->usage & VK_IMAGE_USAGE_TRANSFER_DST_BIT))
        return result;
    image_info *entry = malloc(sizeof(*entry));
    if (entry) {
        pthread_mutex_lock(&mutex);
        *entry = (image_info){.handle = *image, .device = device, .link = images};
        images = entry;
        pthread_mutex_unlock(&mutex);
    }
    return result;
}

static VKAPI_ATTR void VKAPI_CALL destroy_image(VkDevice device, VkImage image,
                                               const VkAllocationCallbacks *allocator)
{
    device_info state = find_device(device);
    pthread_mutex_lock(&mutex);
    for (image_info **i = &images; *i; i = &(*i)->link) {
        image_info *entry = *i;
        if (entry->handle != image || entry->device != device) continue;
        *i = entry->link;
        free(entry);
        break;
    }
    pthread_mutex_unlock(&mutex);
    ((PFN_vkDestroyImage)state.next(device, "vkDestroyImage"))(device, image, allocator);
}

static VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL gdpa(VkDevice device, const char *name);
static VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL gipa(VkInstance instance, const char *name);

static PFN_vkVoidFunction dispatch_device(const char *name)
{
    if (!strcmp(name, "vkGetDeviceProcAddr")) return (PFN_vkVoidFunction)gdpa;
    if (!strcmp(name, "vkDestroyDevice")) return (PFN_vkVoidFunction)destroy_device;
    if (!strcmp(name, "vkCreateImage")) return (PFN_vkVoidFunction)create_image;
    if (!strcmp(name, "vkDestroyImage")) return (PFN_vkVoidFunction)destroy_image;
    return NULL;
}

static VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL gdpa(VkDevice device, const char *name)
{
    PFN_vkVoidFunction local = dispatch_device(name);
    if (local) return local;
    device_info state = find_device(device);
    return state.next ? state.next(device, name) : NULL;
}

static VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL gipa(VkInstance instance, const char *name)
{
    if (!strcmp(name, "vkGetInstanceProcAddr")) return (PFN_vkVoidFunction)gipa;
    if (!strcmp(name, "vkCreateInstance")) return (PFN_vkVoidFunction)create_instance;
    if (!instance) return NULL;
    if (!strcmp(name, "vkDestroyInstance")) return (PFN_vkVoidFunction)destroy_instance;
    if (!strcmp(name, "vkCreateDevice")) return (PFN_vkVoidFunction)create_device;
    PFN_vkVoidFunction local = dispatch_device(name);
    if (local) return local;
    instance_info state = find_instance(instance);
    return state.next ? state.next(instance, name) : NULL;
}

static VKAPI_ATTR PFN_vkVoidFunction VKAPI_CALL physical_gipa(VkInstance instance, const char *name)
{
    const instance_info state = find_instance(instance);
    return state.next_physical ? state.next_physical(instance, name) : NULL;
}

__attribute__((visibility("default")))
VKAPI_ATTR VkResult VKAPI_CALL vkNegotiateLoaderLayerInterfaceVersion(VkNegotiateLayerInterface *info)
{
    if (info->loaderLayerInterfaceVersion < 2) return VK_ERROR_INITIALIZATION_FAILED;
    info->loaderLayerInterfaceVersion = 2;
    info->pfnGetInstanceProcAddr = gipa;
    info->pfnGetDeviceProcAddr = gdpa;
    info->pfnGetPhysicalDeviceProcAddr = physical_gipa;
    return VK_SUCCESS;
}
