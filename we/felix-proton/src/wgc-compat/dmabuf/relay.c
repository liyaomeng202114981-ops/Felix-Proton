// SPDX-License-Identifier: BSD-3-Clause
// Copyright 2026 Felix Li, with OpenAI Codex assistance.
#define _GNU_SOURCE
#include "relay.h"
#include <errno.h>
#include <poll.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

int relay_open(const char *path)
{
    struct sockaddr_un address = {.sun_family = AF_UNIX};
    if (strlen(path) >= sizeof(address.sun_path)) return -1;
    strcpy(address.sun_path, path);
    int fd = socket(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);
    if (fd < 0) return -1;
    if (bind(fd, (const struct sockaddr *)&address, sizeof(address)) || listen(fd, 1)) {
        close(fd);
        return -1;
    }
    return fd;
}

int relay_frame(int listening, int *client, int frame_fd, char source_request, const struct window_buffer *frame)
{
    if (*client < 0) {
        *client = accept4(listening, NULL, NULL, SOCK_CLOEXEC | SOCK_NONBLOCK);
        if (*client < 0) return errno == EAGAIN ? 0 : -1;
    }
    char request;
    const ssize_t bytes = recv(*client, &request, 1, 0);
    if (bytes < 0 && errno == EAGAIN) return 0;
    if (!bytes) {
        close(*client);
        *client = -1;
        return 0;
    }
    if (bytes != 1 || request != source_request) {
        // Reject the consumer before any descriptor can cross source types.
        close(*client);
        *client = -1;
        return 0;
    }
    struct iovec data = {.iov_base = (void *)frame, .iov_len = sizeof(*frame)};
    union { struct cmsghdr align; char bytes[CMSG_SPACE(sizeof(int))]; } control = {0};
    struct msghdr msg = {.msg_iov = &data, .msg_iovlen = 1,
        .msg_control = control.bytes, .msg_controllen = sizeof(control.bytes)};
    struct cmsghdr *fd_msg = CMSG_FIRSTHDR(&msg);
    fd_msg->cmsg_level = SOL_SOCKET;
    fd_msg->cmsg_type = SCM_RIGHTS;
    fd_msg->cmsg_len = CMSG_LEN(sizeof(int));
    memcpy(CMSG_DATA(fd_msg), &frame_fd, sizeof(frame_fd));
    if (sendmsg(*client, &msg, MSG_NOSIGNAL) != sizeof(*frame)) {
        if (errno == EPIPE || errno == ECONNRESET) {
            // SOCK_SEQPACKET did not deliver the descriptor.
            close(*client);
            *client = -1;
            return 0;
        }
        return -1;
    }
    struct pollfd ack = {.fd = *client, .events = POLLIN};
    if (poll(&ack, 1, 2000) != 1 || recv(*client, &request, 1, 0) != 1 || request != LEASE_DONE)
        return -1;
    return 1;
}
