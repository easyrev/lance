#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <execinfo.h>
#include <fcntl.h>
#include <limits.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>

static const char *absolute_path(int dirfd, const char *path, char *resolved) {
    if (path[0] == '/') return path;
    char parent[PATH_MAX];
    if (dirfd == AT_FDCWD) {
        if (!getcwd(parent, sizeof(parent))) return path;
    } else {
        char descriptor[64];
        snprintf(descriptor, sizeof(descriptor), "/proc/self/fd/%d", dirfd);
        ssize_t size = readlink(descriptor, parent, sizeof(parent) - 1);
        if (size < 0) return path;
        parent[size] = '\0';
    }
    size_t length = strlen(parent);
    if (length + strlen(path) + 2 > PATH_MAX) return path;
    memcpy(resolved, parent, length);
    resolved[length] = '/';
    strcpy(resolved + length + 1, path);
    return resolved;
}

/* External measurement only: no change to the Lance binary is required. */
static int monitored(const char *path) {
    const char *root = getenv("REPLAY_PROBE_ROOT");
    return root && path && strncmp(path, root, strlen(root)) == 0;
}

static void record(const char *event, const char *path, long size) {
    if (!monitored(path)) return;
    const char *log = getenv("REPLAY_PROBE_LOG");
    if (!log) return;
    int fd = syscall(SYS_openat, AT_FDCWD, log, O_CREAT | O_WRONLY | O_APPEND, 0600);
    if (fd < 0) return;
    char text[4096];
    int n = snprintf(text, sizeof(text), "%s\t%s\t%ld\n", event, path, size);
    if (n > 0) syscall(SYS_write, fd, text, (size_t)n < sizeof(text) ? (size_t)n : sizeof(text) - 1);
    if (strcmp(event, "mkdir") == 0 && getenv("REPLAY_PROBE_STACK")) {
        void *frames[24];
        int count = backtrace(frames, 24);
        for (int i = 1; i < count; ++i) {
            Dl_info info;
            if (dladdr(frames[i], &info)) {
                n = snprintf(text, sizeof(text), "frame\t%s\t%p\t%s\n",
                             info.dli_fname,
                             (void *)((char *)frames[i] - (char *)info.dli_fbase),
                             info.dli_sname ? info.dli_sname : "?");
                if (n > 0) syscall(SYS_write, fd, text, (size_t)n < sizeof(text) ? (size_t)n : sizeof(text) - 1);
            }
        }
    }
    syscall(SYS_close, fd);
}

int mkdir(const char *path, mode_t mode) {
    int result = syscall(SYS_mkdirat, AT_FDCWD, path, mode);
    int saved_errno = errno;
    if (result == 0) record("mkdir", path, 0);
    errno = saved_errno;
    return result;
}

int mkdirat(int dirfd, const char *path, mode_t mode) {
    int result = syscall(SYS_mkdirat, dirfd, path, mode);
    int saved_errno = errno;
    char resolved[PATH_MAX];
    if (result == 0) record("mkdir", absolute_path(dirfd, path, resolved), 0);
    errno = saved_errno;
    return result;
}

int unlink(const char *path) {
    int saved_errno = errno;
    struct stat st;
    if (monitored(path) && stat(path, &st) == 0) record("unlink", path, st.st_size);
    errno = saved_errno;
    return syscall(SYS_unlinkat, AT_FDCWD, path, 0);
}

int unlinkat(int dirfd, const char *path, int flags) {
    int saved_errno = errno;
    struct stat st;
    char resolved[PATH_MAX];
    const char *full_path = absolute_path(dirfd, path, resolved);
    if (monitored(full_path) && fstatat(dirfd, path, &st, 0) == 0)
        record("unlink", full_path, st.st_size);
    errno = saved_errno;
    return syscall(SYS_unlinkat, dirfd, path, flags);
}
