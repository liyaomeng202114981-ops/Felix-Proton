// SPDX-License-Identifier: BSD-3-Clause
// Copyright 2026 Felix Li, with OpenAI Codex assistance.
#define _GNU_SOURCE
#include "composite.h"
#include "clock.h"
#include "layer.h"
#include <errno.h>
#include <inttypes.h>
#include <poll.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <sys/un.h>
#include <unistd.h>

#define IMPORT_CACHE 16
typedef struct {
    dev_t device;
    ino_t inode;
    struct window_buffer properties;
    VkImage image;
    VkDeviceMemory memory;
} Imported;

typedef struct {
    int socket, fd;
    char source_request;
    bool requested;
    unsigned next_import;
    struct window_buffer frame;
    struct gpu gpu;
    struct composite composite;
    Imported buffers[IMPORT_CACHE];
} Consumer;

static void lease_failure(const char *stage, int result, const struct gpu_call *args)
{
    const char *path = getenv("FELIX_WGC_DIAG_FILE");
    if (!path) return;
    FILE *log = fopen(path, "a");
    if (!log) return;
    fprintf(log, "lease %s status=%d crop=%ux%u target=%ux%u modifier=%016llx\n",
            stage, result, args->frame.crop_width, args->frame.crop_height,
            args->width, args->height, (unsigned long long)args->frame.modifier);
    fclose(log);
}

static int32_t open_consumer(void *opaque)
{
    struct gpu_call *args = opaque;
    const char *path = getenv("FELIX_WGC_GPU_SOCKET");
    struct sockaddr_un address = {.sun_family = AF_UNIX};
    const bool dynamic = args->source != GPU_SOURCE_STATIC;
    if (dynamic) {
        const char *directory = getenv("FELIX_WGC_AUTO_DIR");
        if (!directory || directory[0] != '/') return -1;
        int length;
        if (args->source >= GPU_SOURCE_FIRST_WINDOW)
            length = snprintf(address.sun_path, sizeof(address.sun_path), "%s/window/%" PRIu32 "/frames.sock",
                              directory, args->source);
        else
            length = snprintf(address.sun_path, sizeof(address.sun_path), "%s/%s/frames.sock",
                              directory, args->source == GPU_SOURCE_MONITOR ? "monitor" : "window");
        if (length < 0 || (size_t)length >= sizeof(address.sun_path)) return -1;
    } else {
        if (!path || strlen(path) >= sizeof(address.sun_path)) return -1;
        strcpy(address.sun_path, path);
    }
    const int fd = socket(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0);
    if (fd < 0) return -2;
    struct ucred peer;
    socklen_t size = sizeof(peer);
    if (connect(fd, (const struct sockaddr *)&address, sizeof(address))) {
        int failure = errno;
        close(fd);
        return dynamic && (failure == ENOENT || failure == ECONNREFUSED) ? GPU_SOURCE_PENDING : -3;
    }
    if (getsockopt(fd, SOL_SOCKET, SO_PEERCRED, &peer, &size) || peer.uid != getuid()) {
        close(fd);
        return -3;
    }
    const char *source = getenv("FELIX_WGC_GPU_SOURCE");
    Consumer *state = calloc(1, sizeof(*state));
    if (!state) { close(fd); return -4; }
    state->socket = fd;
    state->fd = -1;
    const bool monitor = dynamic ? args->source == GPU_SOURCE_MONITOR : source && !strcmp(source, "monitor");
    state->source_request = monitor ? MONITOR_REQUEST : WINDOW_REQUEST;
    args->context = (uintptr_t)state;
    return 0;
}

static int32_t next_frame(void *opaque)
{
    struct gpu_call *args = opaque;
    Consumer *state = (Consumer *)(uintptr_t)args->context;
    if (!state || state->fd >= 0) return -1;
    if (!state->requested) {
        if (send(state->socket, &state->source_request, 1, MSG_NOSIGNAL) != 1) return -2;
        state->requested = true;
    }
    struct pollfd incoming = {.fd = state->socket, .events = POLLIN};
    const int available = poll(&incoming, 1, 24);
    if (!available || (available < 0 && errno == EINTR)) return 1;
    if (available < 0 || !(incoming.revents & POLLIN)) return -3;
    struct iovec data = {.iov_base=&state->frame, .iov_len=sizeof(state->frame)};
    union { struct cmsghdr align; char bytes[CMSG_SPACE(sizeof(int))]; } ancillary = {0};
    struct msghdr msg = {.msg_iov=&data, .msg_iovlen=1, .msg_control=ancillary.bytes,
                         .msg_controllen=sizeof(ancillary.bytes)};
    const ssize_t bytes = recvmsg(state->socket, &msg, MSG_CMSG_CLOEXEC);
    state->requested = false;
    struct cmsghdr *control = CMSG_FIRSTHDR(&msg);
    int fd = -1;
    if (control && control->cmsg_len == CMSG_LEN(sizeof(fd)) &&
        control->cmsg_level == SOL_SOCKET && control->cmsg_type == SCM_RIGHTS)
        memcpy(&fd, CMSG_DATA(control), sizeof(fd));
    const struct window_buffer *frame = &state->frame;
    if (bytes != sizeof(state->frame) || fd < 0 || msg.msg_flags & (MSG_TRUNC | MSG_CTRUNC) ||
        !frame->width || !frame->height || frame->width > 8192 || frame->height > 8192 ||
        frame->x >= frame->width || frame->y >= frame->height ||
        !frame->crop_width || !frame->crop_height || frame->crop_width > frame->width - frame->x ||
        frame->crop_height > frame->height - frame->y || frame->stride < frame->width * 4) {
        if (fd >= 0) close(fd);
        return -4;
    }
    state->fd = fd;
    args->frame = state->frame;
    return 0;
}

static int bind_gpu(Consumer *consumer, const struct gpu_call *args)
{
    struct gpu *gpu = &consumer->gpu;
    struct felix_device dev;
    if (!felix_image_device((VkImage)(uintptr_t)args->image, &dev)) return -20;
    VkDevice device = dev.handle;
    if (gpu->device)
        return gpu->device == device && gpu->family == args->family && gpu->fence ? 0 : -21;

    const char *node_path = getenv("FELIX_WGC_GPU_RENDER_NODE");
    struct stat node;
    if (!node_path || stat(node_path, &node) || !S_ISCHR(node.st_mode) || !dev.drm.hasRender ||
        dev.drm.renderMajor != major(node.st_rdev) || dev.drm.renderMinor != minor(node.st_rdev))
        return -22;

    gpu->device = device;
    gpu->family = args->family;
    gpu->get_fd_properties = (PFN_vkGetMemoryFdPropertiesKHR)
        dev.next(device, "vkGetMemoryFdPropertiesKHR");
    vkGetDeviceQueue(device, args->family, args->index, &gpu->queue);
    if (!gpu->get_fd_properties || !gpu->queue) return -23;
    gpu->memory = dev.memory;
    const VkCommandPoolCreateInfo pool = {.sType=VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,
        .queueFamilyIndex=gpu->family, .flags=VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT};
    const VkCommandBufferAllocateInfo defaults = {.sType=VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
        .level=VK_COMMAND_BUFFER_LEVEL_PRIMARY, .commandBufferCount=1};
    const VkFenceCreateInfo fence = {.sType=VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
    if (vkCreateCommandPool(device, &pool, NULL, &gpu->pool) != VK_SUCCESS) return -24;
    VkCommandBufferAllocateInfo command = defaults;
    command.commandPool = gpu->pool;
    if (vkAllocateCommandBuffers(device, &command, &gpu->command) != VK_SUCCESS ||
        vkCreateFence(device, &fence, NULL, &gpu->fence) != VK_SUCCESS) return -25;
    if (args->trace && args->family < sizeof(dev.timestamp_bits) / sizeof(dev.timestamp_bits[0]) &&
        dev.timestamp_bits[args->family] > 0 && dev.timestamp_bits[args->family] <= 64) {
        const VkQueryPoolCreateInfo queries = {.sType=VK_STRUCTURE_TYPE_QUERY_POOL_CREATE_INFO,
            .queryType=VK_QUERY_TYPE_TIMESTAMP, .queryCount=2};
        if (vkCreateQueryPool(device, &queries, NULL, &gpu->timestamps) == VK_SUCCESS) {
            gpu->timestamp_period = dev.timestamp_period;
            gpu->timestamp_bits = dev.timestamp_bits[args->family];
        }
    }
    return composite_init(&consumer->composite, gpu->device);
}

static void discard_import(VkDevice gpu, Imported *entry)
{
    if (entry->image) vkDestroyImage(gpu, entry->image, NULL);
    if (entry->memory) vkFreeMemory(gpu, entry->memory, NULL);
    *entry = (Imported){0};
}

static int lease_image(Consumer *state, VkImage *source)
{
    struct stat info;
    if (fstat(state->fd, &info)) return -30;
    const struct window_buffer *f = &state->frame;
    for (unsigned i = 0; i < IMPORT_CACHE; ++i) {
        const Imported *entry = &state->buffers[i];
        const struct window_buffer *e = &entry->properties;
        if (entry->image && info.st_dev == entry->device && info.st_ino == entry->inode &&
            f->width == e->width && f->height == e->height && f->stride == e->stride &&
            f->offset == e->offset && f->modifier == e->modifier) {
            *source = entry->image;
            return 0;
        }
    }
    Imported *entry = state->buffers + (state->next_import++ % IMPORT_CACHE);
    discard_import(state->gpu.device, entry);
    const int result = gpu_import(&state->gpu, state->fd, f, &entry->image, &entry->memory);
    if (result) {
        discard_import(state->gpu.device, entry);
        return result;
    }
    entry->device = info.st_dev;
    entry->inode = info.st_ino;
    entry->properties = *f;
    *source = entry->image;
    return 0;
}

static int32_t copy_lease(void *opaque)
{
    struct gpu_call *args = opaque;
    Consumer *state = (Consumer *)(uintptr_t)args->context;
    if (!state || state->fd < 0 || !args->width || !args->height ||
        memcmp(&state->frame, &args->frame, sizeof(state->frame)))
        return -1;
    int result = bind_gpu(state, args);
    VkImage source;
    args->timing = (struct gpu_timing){0};
    if (!result) {
        const uint64_t start = args->trace ? monotonic_ns() : 0;
        result = gpu_acquire(state->fd);
        if (args->trace) args->timing.acquire_ns = monotonic_ns() - start;
    }
    if (!result) {
        const uint64_t start = args->trace ? monotonic_ns() : 0;
        result = lease_image(state, &source);
        if (args->trace) args->timing.import_ns = monotonic_ns() - start;
    }
    if (!result) result = composite_crop(&state->composite, &state->gpu, source, args);
    close(state->fd);
    state->fd = -1;
    const char reply = result ? LEASE_FAILED : LEASE_DONE;
    if (result) lease_failure("copy", result, args);
    const ssize_t n = send(state->socket, &reply, 1, MSG_NOSIGNAL);
    return result ? result : n == 1 ? 0 : -2;
}

static int32_t close_consumer(void *opaque)
{
    struct gpu_call *args = opaque;
    Consumer *state = (Consumer *)(uintptr_t)args->context;
    if (!state) return 0;
    if (state->fd >= 0) {
        lease_failure("abandoned", -1, args);
        const char rejected = LEASE_FAILED;
        send(state->socket, &rejected, 1, MSG_NOSIGNAL);
        close(state->fd);
    } else if (state->requested) {
        // A final lease may be in flight, but no descriptor was read by
        // this consumer and no GPU operation has used it.
        const char discarded = LEASE_DONE;
        send(state->socket, &discarded, 1, MSG_NOSIGNAL);
    }
    close(state->socket);
    if (state->gpu.device) {
        composite_finish(&state->composite, state->gpu.device);
        for (unsigned i = 0; i < IMPORT_CACHE; ++i)
            discard_import(state->gpu.device, &state->buffers[i]);
        vkDestroyQueryPool(state->gpu.device, state->gpu.timestamps, NULL);
        vkDestroyFence(state->gpu.device, state->gpu.fence, NULL);
        vkDestroyCommandPool(state->gpu.device, state->gpu.pool, NULL);
    }
    free(state);
    args->context = 0;
    return 0;
}

__attribute__((visibility("default")))
int32_t (*const __wine_unix_call_funcs[])(void *) = {
    open_consumer, next_frame, copy_lease, close_consumer,
};
