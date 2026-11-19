// SPDX-License-Identifier: BSD-3-Clause
// Copyright 2026 Felix Li, with OpenAI Codex assistance.
#include "gpu.h"
#include "clock.h"
#include "relay.h"

#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <limits.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <xf86drm.h>

#include <pipewire/pipewire.h>
#include <spa/param/video/format-utils.h>
#include <spa/pod/builder.h>
#include <spa/pod/dynamic.h>

struct capture {
    struct pw_main_loop *loop;
    struct pw_stream *stream;
    struct gpu gpu;
    struct spa_video_info_raw info;
    unsigned successes, errors;
    unsigned incoming, valid;
    uint64_t period_start;
    bool trace, monitor;
    bool reported_sync;
    const char *start_gate;
    const char *size_path;
    const char *lease_path;
    struct spa_source *initial_timer;
    struct pw_buffer *initial_buffer;
    struct spa_meta_sync_timeline *initial_timeline;
    struct window_buffer initial_frame;
    int listener, client;
    int sync_device;
    struct window_buffer last;
    uint32_t pixels[3];
};

static int open_sync_device(const char *node)
{
    const int fd = open(node, O_RDWR | O_CLOEXEC);
    uint64_t supported = 0;
    if (fd < 0) return -1;
    if (!drmGetCap(fd, DRM_CAP_SYNCOBJ_TIMELINE, &supported) && supported)
        return fd;
    close(fd);
    return -1;
}

static int sync_point(int device, int fd, uint64_t point, bool acquire)
{
    uint32_t handle;
    int status = drmSyncobjFDToHandle(device, fd, &handle);
    if (status) return status;
    if (acquire) {
        const int64_t deadline = monotonic_ns() + 1500000000;
        status = drmSyncobjTimelineWait(device, &handle, &point, 1, deadline,
                                        DRM_SYNCOBJ_WAIT_FLAGS_WAIT_FOR_SUBMIT, NULL);
    } else {
        status = drmSyncobjTimelineSignal(device, &handle, &point, 1);
    }
    drmSyncobjDestroy(device, handle);
    return status;
}

static int acquire_frame(struct capture *state, struct spa_buffer *buffer,
                         struct spa_meta_sync_timeline **timeline)
{
    if (state->sync_device < 0 || buffer->n_datas == 1) return 0;
    if (buffer->n_datas != 3 || buffer->datas[1].type != SPA_DATA_SyncObj ||
        buffer->datas[2].type != SPA_DATA_SyncObj ||
        buffer->datas[1].fd < 0 || buffer->datas[2].fd < 0)
        return -EINVAL;
    *timeline = spa_buffer_find_meta_data(buffer, SPA_META_SyncTimeline, sizeof(**timeline));
    if (!*timeline || !(*timeline)->acquire_point ||
        (*timeline)->release_point <= (*timeline)->acquire_point)
        return -EINVAL;
    return sync_point(state->sync_device, buffer->datas[1].fd, (*timeline)->acquire_point, true);
}

static void stop(void *opaque, int sig)
{
    struct capture *state = opaque;
    (void)sig;
    pw_main_loop_quit(state->loop);
}

static void stream_state(void *opaque, enum pw_stream_state previous,
                         enum pw_stream_state current, const char *message)
{
    struct capture *state = opaque;
    (void)previous;
    printf("PIPEWIRE %s\n", pw_stream_state_as_string(current));
    if (current == PW_STREAM_STATE_ERROR || current == PW_STREAM_STATE_UNCONNECTED) {
        if (message) fprintf(stderr, "PipeWire stream: %s\n", message);
        pw_main_loop_quit(state->loop);
    }
}

static void on_format(void *opaque, uint32_t id, const struct spa_pod *param)
{
    struct capture *state = opaque;
    if (id != SPA_PARAM_Format || !param)
        return;
    if (spa_format_video_raw_parse(param, &state->info) < 0 ||
        !(state->info.flags & SPA_VIDEO_FLAG_MODIFIER) ||
        (state->info.format != SPA_VIDEO_FORMAT_BGRx && state->info.format != SPA_VIDEO_FORMAT_BGRA)) {
        pw_stream_set_error(state->stream, -EINVAL, "Expected a DMA-BUF BGRx or BGRA format");
        return;
    }
    printf("DMABUF_FORMAT %ux%u modifier=%016" PRIx64 " spa=%u\n", state->info.size.width,
           state->info.size.height, state->info.modifier, state->info.format);
    uint8_t buffer[1024];
    struct spa_pod_builder builder = SPA_POD_BUILDER_INIT(buffer, sizeof(buffer));
    const struct spa_pod *params[4];
    unsigned count = 0;
    if (state->sync_device >= 0) {
        struct spa_pod_frame sync_buffers;
        spa_pod_builder_push_object(&builder, &sync_buffers, SPA_TYPE_OBJECT_ParamBuffers, SPA_PARAM_Buffers);
        spa_pod_builder_add(&builder, SPA_PARAM_BUFFERS_dataType, SPA_POD_Int(1u << SPA_DATA_DmaBuf), 0);
        spa_pod_builder_prop(&builder, SPA_PARAM_BUFFERS_metaType, SPA_POD_PROP_FLAG_MANDATORY);
        spa_pod_builder_int(&builder, 1u << SPA_META_SyncTimeline);
        params[count++] = spa_pod_builder_pop(&builder, &sync_buffers);
        params[count++] = spa_pod_builder_add_object(&builder, SPA_TYPE_OBJECT_ParamMeta, SPA_PARAM_Meta,
            SPA_PARAM_META_type, SPA_POD_Id(SPA_META_SyncTimeline),
            SPA_PARAM_META_size, SPA_POD_Int(sizeof(struct spa_meta_sync_timeline)));
    }
    params[count++] = spa_pod_builder_add_object(&builder, SPA_TYPE_OBJECT_ParamBuffers, SPA_PARAM_Buffers,
            SPA_PARAM_BUFFERS_buffers, SPA_POD_CHOICE_RANGE_Int(8, 2, 16),
            SPA_PARAM_BUFFERS_blocks, SPA_POD_Int(1),
            SPA_PARAM_BUFFERS_dataType, SPA_POD_CHOICE_FLAGS_Int(1u << SPA_DATA_DmaBuf));
    params[count++] = spa_pod_builder_add_object(&builder, SPA_TYPE_OBJECT_ParamMeta, SPA_PARAM_Meta,
            SPA_PARAM_META_type, SPA_POD_Id(SPA_META_VideoCrop),
            SPA_PARAM_META_size, SPA_POD_Int(sizeof(struct spa_meta_region)));
    pw_stream_update_params(state->stream, params, count);
}

static bool metadata(struct capture *state, struct spa_buffer *buffer,
                     bool explicit_sync, struct window_buffer *f)
{
    if (buffer->n_datas != (explicit_sync ? 3u : 1u) || buffer->datas[0].type != SPA_DATA_DmaBuf ||
        buffer->datas[0].fd < 0 || !buffer->datas[0].chunk)
        return false;
    const struct spa_data *data = &buffer->datas[0];
    const struct spa_chunk *chunk = data->chunk;
    if (!chunk->size || (chunk->flags & SPA_CHUNK_FLAG_CORRUPTED) || chunk->stride <= 0)
        return false;
    const struct spa_meta_region *crop = spa_buffer_find_meta_data(buffer, SPA_META_VideoCrop, sizeof(*crop));
    const uint32_t w = state->info.size.width, h = state->info.size.height;
    if (!w || !h || w > 8192 || h > 8192 || (uint64_t)data->mapoffset + chunk->offset > UINT32_MAX)
        return false;
    *f = (struct window_buffer){.width=w, .height=h, .crop_width=w, .crop_height=h,
        .stride=chunk->stride, .offset=data->mapoffset+chunk->offset, .modifier=state->info.modifier};
    if (!crop || !spa_meta_region_is_valid(crop))
        return state->monitor;
    const struct spa_region rect = crop->region;
    if (rect.position.x < 0 || rect.position.y < 0 || (uint32_t)rect.position.x >= w ||
        (uint32_t)rect.position.y >= h || rect.size.width > w - (uint32_t)rect.position.x ||
        rect.size.height > h - (uint32_t)rect.position.y)
        return false;
    f->x = rect.position.x;
    f->y = rect.position.y;
    f->crop_width = rect.size.width;
    f->crop_height = rect.size.height;
    return true;
}

static void trace_source(struct capture *state)
{
    if (!state->trace) return;
    const uint64_t now = monotonic_ns();
    if (!state->period_start) state->period_start = now;
    if (now - state->period_start < 2000000000ull) return;
    printf("FELIX_PW elapsed_ms=%" PRIu64 " incoming=%u valid=%u leases=%u errors=%u\n",
           (now - state->period_start) / 1000000, state->incoming, state->valid,
           state->successes, state->errors);
    state->period_start = now;
    state->incoming = state->valid = 0;
}

static void report_source_size(struct capture *state, const struct window_buffer *frame)
{
    if (!state->size_path) return;
    char pending[PATH_MAX];
    const int length = snprintf(pending, sizeof(pending), "%s.new", state->size_path);
    if (length < 0 || (size_t)length >= sizeof(pending)) return;
    FILE *file = fopen(pending, "w");
    if (file) {
        const int wrote = fprintf(file, "%u %u\n", frame->crop_width, frame->crop_height);
        if (!fclose(file) && wrote > 0 && !rename(pending, state->size_path))
            state->size_path = NULL;
    }
}

static bool release_buffer(struct capture *state, struct pw_buffer *buffer,
                           struct spa_meta_sync_timeline *timeline)
{
    if (timeline) {
        // A successful lease ACK is sent after the consumer's GPU fence.
        if (sync_point(state->sync_device, buffer->buffer->datas[2].fd, timeline->release_point, false)) {
            ++state->errors;
            pw_stream_set_error(state->stream, -EIO, "Failed to release the window DMA-BUF timeline point");
            return false;
        }
        timeline->flags &= ~SPA_META_SYNC_TIMELINE_UNSCHEDULED_RELEASE;
    }
    pw_stream_queue_buffer(state->stream, buffer);
    return true;
}

static int deliver_frame(struct capture *state, struct pw_buffer *buffer, const struct window_buffer *frame)
{
    const int result = relay_frame(state->listener, &state->client, buffer->buffer->datas[0].fd,
                                   state->monitor ? MONITOR_REQUEST : WINDOW_REQUEST, frame);
    if (result < 0) {
        ++state->errors;
        pw_stream_set_error(state->stream, -EIO, "GPU consumer failed its DMA-BUF lease");
    } else if (result > 0) {
        if (++state->successes % 120 == 1)
            printf("GPU_LEASES %u %ux%u\n", state->successes, frame->crop_width, frame->crop_height);
        if (state->lease_path) {
            FILE *file = fopen(state->lease_path, "w");
            if (file && !fclose(file)) state->lease_path = NULL;
        }
    }
    return result;
}

static void initial_timer(void *opaque, uint64_t expirations)
{
    struct capture *state = opaque;
    (void)expirations;
    if (!state->initial_buffer) return;
    const int result = deliver_frame(state, state->initial_buffer, &state->initial_frame);
    if (!result) return;
    if (result > 0) release_buffer(state, state->initial_buffer, state->initial_timeline);
    state->initial_buffer = NULL;
    pw_loop_update_timer(pw_main_loop_get_loop(state->loop), state->initial_timer, NULL, NULL, false);
}

static void remove_buffer(void *opaque, struct pw_buffer *buffer)
{
    struct capture *state = opaque;
    if (buffer == state->initial_buffer) {
        state->initial_buffer = NULL;
        pw_loop_update_timer(pw_main_loop_get_loop(state->loop), state->initial_timer, NULL, NULL, false);
    }
}

static void on_frame(void *opaque)
{
    struct capture *state = opaque;
    struct pw_buffer *buffer = pw_stream_dequeue_buffer(state->stream);
    if (!buffer)
        return;
    ++state->incoming;
    struct spa_buffer *raw = buffer->buffer;
    struct spa_meta_sync_timeline *timeline = NULL;
    if (acquire_frame(state, raw, &timeline)) {
        ++state->errors;
        pw_stream_set_error(state->stream, -EIO, "Failed to acquire the window DMA-BUF timeline point");
        return;
    }
    if (!state->monitor && !state->reported_sync) {
        printf("WINDOW_DMA_BUF_SYNC %s\n", timeline ? "explicit" : "implicit");
        state->reported_sync = true;
    }
    if (state->start_gate) {
        if (access(state->start_gate, F_OK)) goto release;
        state->start_gate = NULL;
        puts("DMA-BUF delivery enabled");
    }
    struct window_buffer frame;
    uint32_t pixels[3];
    if (metadata(state, raw, timeline != NULL, &frame)) {
        ++state->valid;
        report_source_size(state, &frame);
        const int fd = buffer->buffer->datas[0].fd;
        if (state->listener >= 0) {
            if (state->initial_buffer) {
                struct pw_buffer *previous = state->initial_buffer;
                state->initial_buffer = NULL;
                if (!release_buffer(state, previous, state->initial_timeline)) return;
            }
            const int result = deliver_frame(state, buffer, &frame);
            if (result < 0) return; /* Disconnect without recycling an unacknowledged buffer. */
            if (state->initial_timer) {
                struct pw_loop *loop = pw_main_loop_get_loop(state->loop);
                if (!result && state->lease_path) {
                    struct timespec period = {.tv_nsec = 20000000};
                    if (!pw_loop_update_timer(loop, state->initial_timer, &period, &period, false)) {
                        state->initial_buffer = buffer;
                        state->initial_frame = frame;
                        state->initial_timeline = timeline;
                        trace_source(state);
                        return;
                    }
                }
                pw_loop_update_timer(loop, state->initial_timer, NULL, NULL, false);
            }
            goto release;
        }
        const int result = gpu_sample(&state->gpu, fd, &frame, pixels);
        if (result) {
            if (++state->errors == 1)
                fprintf(stderr, "IMPORT_OR_READ_ERROR %d\n", result);
            if (state->errors >= 5)
                pw_stream_set_error(state->stream, -EIO, "Repeated GPU import or sync failure");
        } else {
            state->successes++;
            if (memcmp(state->pixels, pixels, sizeof(pixels)) ||
                state->last.crop_width != frame.crop_width || state->last.crop_height != frame.crop_height) {
                printf("DMABUF_FRAME %u %ux%u crop %u,%u %ux%u stride=%u offset=%u mod=%016" PRIx64
                       " rgb=%06x,%06x,%06x\n", state->successes, frame.width, frame.height, frame.x,
                       frame.y, frame.crop_width, frame.crop_height, frame.stride, frame.offset,
                       frame.modifier, pixels[0], pixels[1], pixels[2]);
                memcpy(state->pixels, pixels, sizeof(pixels));
                state->last = frame;
            }
        }
    }
release:
    if (!release_buffer(state, buffer, timeline)) return;
    trace_source(state);
}

static const struct pw_stream_events events = {
    PW_VERSION_STREAM_EVENTS,
    .state_changed = stream_state, .param_changed = on_format, .process = on_frame,
    .remove_buffer = remove_buffer,
};

static const struct spa_pod *build_offer(struct spa_pod_builder *builder,
                                         const struct gpu *gpu, uint32_t format)
{
    struct spa_pod_frame object, choice;
    spa_pod_builder_push_object(builder, &object, SPA_TYPE_OBJECT_Format, SPA_PARAM_EnumFormat);
    spa_pod_builder_prop(builder, SPA_FORMAT_mediaType, 0);
    spa_pod_builder_id(builder, SPA_MEDIA_TYPE_video);
    spa_pod_builder_prop(builder, SPA_FORMAT_mediaSubtype, 0);
    spa_pod_builder_id(builder, SPA_MEDIA_SUBTYPE_raw);
    spa_pod_builder_prop(builder, SPA_FORMAT_VIDEO_format, 0);
    spa_pod_builder_id(builder, format);
    spa_pod_builder_prop(builder, SPA_FORMAT_VIDEO_modifier,
        SPA_POD_PROP_FLAG_MANDATORY | SPA_POD_PROP_FLAG_DONT_FIXATE);
    spa_pod_builder_push_choice(builder, &choice, SPA_CHOICE_Enum, 0);
    spa_pod_builder_long(builder, gpu->modifiers[0]);
    for (uint32_t i = 0; i < gpu->modifier_count; ++i)
        spa_pod_builder_long(builder, gpu->modifiers[i]);
    spa_pod_builder_pop(builder, &choice);
    spa_pod_builder_add(builder, SPA_FORMAT_VIDEO_size, SPA_POD_CHOICE_RANGE_Rectangle(
        &SPA_RECTANGLE(1280, 720), &SPA_RECTANGLE(1, 1), &SPA_RECTANGLE(8192, 8192)),
        SPA_FORMAT_VIDEO_framerate, SPA_POD_CHOICE_RANGE_Fraction(
        &SPA_FRACTION(30, 1), &SPA_FRACTION(0, 1), &SPA_FRACTION(60, 1)), 0);
    return spa_pod_builder_pop(builder, &object);
}

int main(int argc, char **argv)
{
    const bool monitor = argc == 6 && !strcmp(argv[5], "--monitor");
    if (argc != 2 && argc != 4 && argc != 5 && !monitor) {
        fprintf(stderr, "Usage: %s render-node [pipewire-fd node-id [socket [--monitor]]]\n", argv[0]);
        return 2;
    }
    setvbuf(stdout, NULL, _IOLBF, 0);
    sigset_t signals;
    sigemptyset(&signals);
    sigaddset(&signals, SIGINT);
    sigaddset(&signals, SIGTERM);
    if (sigprocmask(SIG_BLOCK, &signals, NULL)) return 1;
    struct capture state = {
        .listener=-1, .client=-1, .trace=getenv("FELIX_WGC_TIMING") != NULL, .monitor=monitor,
        .sync_device=-1,
        .start_gate=getenv("FELIX_WGC_START_GATE"),
        .size_path=getenv("FELIX_WGC_SIZE_FILE"),
        .lease_path=getenv("FELIX_WGC_FIRST_LEASE_FILE"),
    };
    if (argc >= 5 && (state.listener = relay_open(argv[4])) < 0) {
        perror("GPU relay listen");
        return 1;
    }
    int result = 1;
    if (gpu_init(&state.gpu, argv[1])) {
        fprintf(stderr, "Unable to create a DMA-BUF Vulkan importer for %s\n", argv[1]);
        goto done;
    }
    printf("IMPORTABLE_MODIFIERS %u\n", state.gpu.modifier_count);
    if (argc == 2) { result = 0; goto done; }
    if (!monitor)
        state.sync_device = open_sync_device(argv[1]);
    pw_init(NULL, NULL);
    state.loop = pw_main_loop_new(NULL);
    struct pw_loop *loop = pw_main_loop_get_loop(state.loop);
    pw_loop_add_signal(loop, SIGTERM, stop, &state);
    pw_loop_add_signal(loop, SIGINT, stop, &state);
    struct pw_context *context = pw_context_new(loop, NULL, 0);
    struct pw_core *core = pw_context_connect_fd(context, atoi(argv[2]), NULL, 0);
    if (!core) goto pipewire_done;
    state.stream = pw_stream_new(core, "Felix WGC DMA-BUF probe",
        pw_properties_new(PW_KEY_MEDIA_TYPE, "Video", PW_KEY_MEDIA_CATEGORY, "Capture", NULL));
    if (!state.stream) goto pipewire_done;
    struct spa_hook listener;
    pw_stream_add_listener(state.stream, &listener, &events, &state);
    if (state.listener >= 0 && state.lease_path && getenv("FELIX_WGC_RETAIN_FIRST"))
        state.initial_timer = pw_loop_add_timer(loop, initial_timer, &state);
    uint8_t storage[4096];
    struct spa_pod_builder builder = SPA_POD_BUILDER_INIT(storage, sizeof(storage));
    const struct spa_pod *offer[] = {build_offer(&builder, &state.gpu, SPA_VIDEO_FORMAT_BGRx),
                                    build_offer(&builder, &state.gpu, SPA_VIDEO_FORMAT_BGRA)};
    if (offer[0] && offer[1] &&
        pw_stream_connect(state.stream, PW_DIRECTION_INPUT, strtoul(argv[3], NULL, 10),
                          PW_STREAM_FLAG_AUTOCONNECT, offer, SPA_N_ELEMENTS(offer)) >= 0)
        pw_main_loop_run(state.loop);
    if (state.initial_buffer) {
        release_buffer(&state, state.initial_buffer, state.initial_timeline);
        state.initial_buffer = NULL;
    }
    if (state.initial_timer) pw_loop_destroy_source(loop, state.initial_timer);
    printf("SUMMARY successful=%u errors=%u\n", state.successes, state.errors);
    result = !state.successes || state.errors;
    pw_stream_destroy(state.stream);
pipewire_done:
    if (core) pw_core_disconnect(core);
    pw_context_destroy(context);
    pw_main_loop_destroy(state.loop);
    pw_deinit();
done:
    if (state.sync_device >= 0) close(state.sync_device);
    gpu_finish(&state.gpu);
    if (state.client >= 0) close(state.client);
    if (state.listener >= 0) {
        close(state.listener);
        unlink(argv[4]);
    }
    return result;
}
