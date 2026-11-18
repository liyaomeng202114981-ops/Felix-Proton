#define WIN32_LEAN_AND_MEAN
#define _WIN32_WINNT 0x0601
#include <windows.h>
#include <windowsx.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum mode { MODE_UNSET, MODE_PLAIN, MODE_FIXED, MODE_BROKEN, MODE_CORRECTED, MODE_FIXED_BROKEN, MODE_BROKEN_COORDS };
static const char *const mode_names[] = {"unset", "plain", "fixed", "broken", "corrected", "fixed-broken", "broken-coords"};
static const char window_class[] = "FelixEdgeFixtureWindow";
static const char child_class[] = "FelixEdgeFixtureChild";
static const LONG initial_width = 640, initial_height = 420, edge = 12;
static enum mode trial_mode;
static HWND main_window, child_window;
static HANDLE finished;
static FILE *events;
static const char *trigger_path;
static DWORD duration_ms = 20000;
static ULONGLONG started;
static RECT last_rect, ready_rect;
static FILETIME last_control_write;
static DWORD last_control_size;
static BOOL have_control;
static BOOL have_rect, synthetic, triggered;
static unsigned records, dropped, geometry_changes, paint_calls, erase_calls;

static BOOL custom_frame(void)
{
    return trial_mode >= MODE_BROKEN;
}

static BOOL fixed_size(void)
{
    return trial_mode == MODE_FIXED || trial_mode == MODE_FIXED_BROKEN;
}

static void log_event(const char *target, const char *event, WPARAM wp, LPARAM lp, LONG value)
{
    if (records >= 2500) { ++dropped; return; }
    ++records;
    fprintf(events, "%llu\t%s\t%s\t%s\t0x%lx\t0x%lx\t%ld\t0\t0\t0\n",
            (unsigned long long)(GetTickCount64() - started), synthetic ? "synthetic" : "pointer-or-system",
            target, event, (unsigned long)wp, (unsigned long)lp, (long)value);
}

static void log_geometry(HWND window, const char *label)
{
    RECT rect;
    if (!GetWindowRect(window, &rect)) return;
    if (have_rect && EqualRect(&last_rect, &rect) && !strcmp(label, "geometry")) return;
    if (have_rect && !EqualRect(&last_rect, &rect)) ++geometry_changes;
    last_rect = rect;
    have_rect = TRUE;
    /* Always keep geometry, including final geometry after motion fills the trace. */
    fprintf(events, "%llu\t%s\tmain\t%s\t0\t0\t%ld\t%ld\t%ld\t%ld\n",
            (unsigned long long)(GetTickCount64() - started), synthetic ? "synthetic" : "pointer-or-system", label,
            (long)rect.left, (long)rect.top, (long)(rect.right - rect.left), (long)(rect.bottom - rect.top));
}

static LRESULT classify_client_point(HWND window, POINT pt)
{
    RECT rect;
    BOOL left, right, top, bottom;
    if (!GetClientRect(window, &rect) || !PtInRect(&rect, pt)) return HTCLIENT;
    left = pt.x < rect.left + edge;
    right = pt.x >= rect.right - edge;
    top = pt.y < rect.top + edge;
    bottom = pt.y >= rect.bottom - edge;
    if (bottom && right) return HTBOTTOMRIGHT;
    if (bottom && left) return HTBOTTOMLEFT;
    if (top && right) return HTTOPRIGHT;
    if (top && left) return HTTOPLEFT;
    if (left) return HTLEFT;
    if (right) return HTRIGHT;
    if (top) return HTTOP;
    if (bottom) return HTBOTTOM;
    return pt.y < rect.top + 34 ? HTCAPTION : HTCLIENT;
}

static LRESULT CALLBACK child_proc(HWND window, UINT message, WPARAM wp, LPARAM lp)
{
    switch (message) {
    case WM_NCHITTEST:
        log_event("child", "WM_NCHITTEST", wp, lp, HTCLIENT);
        return HTCLIENT;
    case WM_LBUTTONDOWN: {
        POINT pt = {GET_X_LPARAM(lp), GET_Y_LPARAM(lp)};
        LRESULT hit = classify_client_point(window, pt);
        LPARAM screen;

        log_event("child", "WM_LBUTTONDOWN", wp, lp, (LONG)hit);
        if (hit == HTCLIENT) return 0;
        ReleaseCapture();
        ClientToScreen(window, &pt);
        screen = MAKELPARAM(pt.x, pt.y);
        if (trial_mode != MODE_CORRECTED) hit = HTCAPTION;
        if (trial_mode == MODE_BROKEN || trial_mode == MODE_FIXED_BROKEN) screen = 0;
        log_event("child", "relay", hit, screen, (LONG)hit);
        SendMessageA(main_window, WM_NCLBUTTONDOWN, hit, screen);
        return 0;
    }
    case WM_PAINT:
        ++paint_calls;
        break;
    case WM_ERASEBKGND:
        ++erase_calls;
        break;
    }
    return DefWindowProcA(window, message, wp, lp);
}

static DWORD WINAPI cancel_synthetic_drag(void *argument)
{
    HWND window = argument;
    if (WaitForSingleObject(finished, 200) == WAIT_TIMEOUT) {
        PostMessageA(window, WM_CANCELMODE, 0, 0);
        PostMessageA(window, WM_KEYDOWN, VK_ESCAPE, 0);
        PostMessageA(window, WM_LBUTTONUP, 0, 0);
    }
    return 0;
}

static void trigger_synthetic(BOOL host_button_held)
{
    HWND target = child_window ? child_window : main_window;
    HANDLE cancel;
    RECT rect;
    POINT pt;
    LRESULT hit;

    if (!GetClientRect(target, &rect)) return;
    pt.x = rect.right - 3;
    pt.y = rect.bottom - 3;
    synthetic = TRUE;
    log_event("main", "file-trigger", 0, 0, 0);
    cancel = host_button_held ? NULL : CreateThread(NULL, 0, cancel_synthetic_drag, main_window, 0, NULL);
    if (cancel || host_button_held) {
        if (child_window) {
            POINT screen = pt;
            ClientToScreen(child_window, &screen);
            SendMessageA(child_window, WM_NCHITTEST, 0, MAKELPARAM(screen.x, screen.y));
            SendMessageA(child_window, WM_LBUTTONDOWN, MK_LBUTTON, MAKELPARAM(pt.x, pt.y));
        } else if (GetWindowRect(main_window, &rect)) {
            LPARAM screen = MAKELPARAM(rect.right - 3, rect.bottom - 3);
            hit = SendMessageA(main_window, WM_NCHITTEST, 0, screen);
            if (hit >= HTLEFT && hit <= HTBOTTOMRIGHT)
                SendMessageA(main_window, WM_NCLBUTTONDOWN, hit, screen);
        }
        if (cancel) CloseHandle(cancel);
    }
    synthetic = FALSE;
}

static void poll_control(HWND window)
{
    WIN32_FILE_ATTRIBUTE_DATA info;
    char command[32] = {0};
    FILE *stream;
    size_t length;

    if (!trigger_path || !GetFileAttributesExA(trigger_path, GetFileExInfoStandard, &info) ||
        (info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) return;
    if (have_control && !CompareFileTime(&last_control_write, &info.ftLastWriteTime) &&
        last_control_size == info.nFileSizeLow) return;
    if (!(stream = fopen(trigger_path, "rb"))) return;
    length = fread(command, 1, sizeof(command) - 1, stream);
    fclose(stream);
    last_control_write = info.ftLastWriteTime;
    last_control_size = info.nFileSizeLow;
    have_control = TRUE;
    while (length && (command[length - 1] == '\r' || command[length - 1] == '\n')) command[--length] = 0;
    if (!length || !strcmp(command, "drag") || !strcmp(command, "replay")) {
        triggered = TRUE;
        trigger_synthetic(!strcmp(command, "replay"));
    } else if (!strcmp(command, "maximize")) {
        log_event("main", "file-maximize", 0, 0, 0);
        ShowWindow(window, SW_MAXIMIZE);
    } else if (!strcmp(command, "restore")) {
        ShowWindow(window, SW_RESTORE);
    } else if (!strcmp(command, "reset")) {
        log_event("main", "file-reset", 0, 0, 0);
        SetWindowPos(window, NULL, ready_rect.left, ready_rect.top,
                     ready_rect.right - ready_rect.left, ready_rect.bottom - ready_rect.top,
                     SWP_NOZORDER | SWP_NOACTIVATE);
        log_geometry(window, "reset-geometry");
    } else if (!strcmp(command, "quit")) {
        log_event("main", "file-quit", 0, 0, 0);
        DestroyWindow(window);
    }
}

static LRESULT CALLBACK window_proc(HWND window, UINT message, WPARAM wp, LPARAM lp)
{
    switch (message) {
    case WM_NCCALCSIZE:
        if (custom_frame()) return 0;
        break;
    case WM_GETMINMAXINFO: {
        LRESULT result = DefWindowProcA(window, message, wp, lp);
        if (fixed_size()) {
            MINMAXINFO *info = (MINMAXINFO *)lp;
            info->ptMinTrackSize.x = info->ptMaxTrackSize.x = initial_width;
            info->ptMinTrackSize.y = info->ptMaxTrackSize.y = initial_height;
        }
        log_event("main", "WM_GETMINMAXINFO", 0, 0, fixed_size());
        return result;
    }
    case WM_NCHITTEST: {
        LRESULT hit = DefWindowProcA(window, message, wp, lp);
        log_event("main", "WM_NCHITTEST", wp, lp, (LONG)hit);
        return hit;
    }
    case WM_LBUTTONDOWN:
        log_event("main", "WM_LBUTTONDOWN", wp, lp, 0);
        break;
    case WM_NCLBUTTONDOWN:
        log_event("main", "WM_NCLBUTTONDOWN", wp, lp, (LONG)wp);
        break;
    case WM_SYSCOMMAND:
        log_event("main", "WM_SYSCOMMAND", wp, lp, (LONG)(wp & 0xfff0));
        break;
    case WM_SIZING:
        log_event("main", "WM_SIZING", wp, 0, (LONG)wp);
        break;
    case WM_ENTERSIZEMOVE:
        log_event("main", "WM_ENTERSIZEMOVE", 0, 0, 0);
        break;
    case WM_EXITSIZEMOVE:
        log_event("main", "WM_EXITSIZEMOVE", 0, 0, 0);
        break;
    case WM_SIZE:
        if (child_window) MoveWindow(child_window, 0, 0, LOWORD(lp), HIWORD(lp), TRUE);
        break;
    case WM_WINDOWPOSCHANGED:
        log_geometry(window, "geometry");
        break;
    case WM_PAINT:
        ++paint_calls;
        break;
    case WM_ERASEBKGND:
        ++erase_calls;
        break;
    case WM_TIMER:
        if (GetTickCount64() - started >= duration_ms) {
            DestroyWindow(window);
        } else poll_control(window);
        return 0;
    case WM_DESTROY:
        log_geometry(window, "final-geometry");
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcA(window, message, wp, lp);
}

static DWORD WINAPI watchdog(void *argument)
{
    HWND window = argument;
    if (WaitForSingleObject(finished, duration_ms + 500) != WAIT_TIMEOUT) return 0;
    PostMessageA(window, WM_CANCELMODE, 0, 0);
    PostMessageA(window, WM_KEYDOWN, VK_ESCAPE, 0);
    PostMessageA(window, WM_LBUTTONUP, 0, 0);
    PostMessageA(window, WM_CLOSE, 0, 0);
    if (WaitForSingleObject(finished, 1500) == WAIT_TIMEOUT) ExitProcess(4);
    return 0;
}

static BOOL register_classes(HINSTANCE instance)
{
    WNDCLASSA wc = {0};
    wc.lpfnWndProc = window_proc;
    wc.hInstance = instance;
    wc.hCursor = LoadCursorA(NULL, IDC_ARROW);
    wc.hbrBackground = (HBRUSH)(COLOR_WINDOW + 1);
    wc.lpszClassName = window_class;
    if (!RegisterClassA(&wc)) return FALSE;
    wc.lpfnWndProc = child_proc;
    wc.hbrBackground = (HBRUSH)(COLOR_BTNFACE + 1);
    wc.lpszClassName = child_class;
    return RegisterClassA(&wc) != 0;
}

int main(int argc, char **argv)
{
    const char *output = NULL, *ready = NULL;
    char title[64];
    HINSTANCE instance = GetModuleHandleA(NULL);
    HANDLE timer_thread;
    FILE *ready_file;
    MSG message;
    RECT rect;
    DWORD style = WS_OVERLAPPEDWINDOW;
    int i, result;

    for (i = 1; i + 1 < argc; i += 2) {
        const char *value = argv[i + 1];
        if (!strcmp(argv[i], "--mode")) {
            unsigned j;
            for (j = MODE_PLAIN; j < sizeof(mode_names) / sizeof(*mode_names); ++j)
                if (!strcmp(value, mode_names[j])) trial_mode = (enum mode)j;
        } else if (!strcmp(argv[i], "--output")) output = value;
        else if (!strcmp(argv[i], "--ready")) ready = value;
        else if (!strcmp(argv[i], "--trigger")) trigger_path = value;
        else if (!strcmp(argv[i], "--duration-ms")) {
            char *end;
            unsigned long parsed;
            errno = 0;
            parsed = strtoul(value, &end, 10);
            if (errno || *end || parsed < 500 || parsed > 60000) break;
            duration_ms = (DWORD)parsed;
        } else break;
    }
    if (i != argc || trial_mode == MODE_UNSET || !output || !ready) {
        fputs("usage: edge_fixture.exe --mode plain|fixed|broken|corrected|fixed-broken|broken-coords --output FILE --ready FILE [--trigger FILE] [--duration-ms N]\n", stderr);
        return 2;
    }
    if (!(events = fopen(output, "wb"))) return 3;
    setvbuf(events, NULL, _IONBF, 0);
    fputs("ms\tinput\ttarget\tevent\twparam\tlparam\tvalue_or_x\ty\twidth\theight\n", events);
    finished = CreateEventA(NULL, TRUE, FALSE, NULL);
    if (!finished || !register_classes(instance)) return 3;
    SetProcessDPIAware();
    started = GetTickCount64();
    snprintf(title, sizeof(title), "FelixEdgeFixture-%s", mode_names[trial_mode]);
    if (custom_frame()) style = WS_POPUP | WS_CAPTION | WS_THICKFRAME | WS_SYSMENU |
                                WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_CLIPCHILDREN | WS_CLIPSIBLINGS;
    main_window = CreateWindowExA(0, window_class, title, style,
                                 140, 110, initial_width, initial_height, NULL, NULL, instance, NULL);
    if (!main_window) return 3;
    if (custom_frame()) {
        if (!GetClientRect(main_window, &rect)) return 3;
        child_window = CreateWindowExA(0, child_class, "", WS_VISIBLE | WS_CHILD,
                                      0, 0, rect.right, rect.bottom, main_window, NULL, instance, NULL);
        if (!child_window) return 3;
    }
    ShowWindow(main_window, SW_SHOWNORMAL);
    UpdateWindow(main_window);
    if (!SetTimer(main_window, 1, 25, NULL)) return 3;
    timer_thread = CreateThread(NULL, 0, watchdog, main_window, 0, NULL);
    if (!timer_thread) return 3;
    if (!(ready_file = fopen(ready, "wb")) || !GetWindowRect(main_window, &ready_rect)) return 3;
    fprintf(ready_file, "pid=0x%lx hwnd=0x%lx tid=0x%lx width=%ld height=%ld\n",
            (unsigned long)GetCurrentProcessId(), (unsigned long)(UINT_PTR)main_window,
            (unsigned long)GetCurrentThreadId(), (long)(ready_rect.right - ready_rect.left),
            (long)(ready_rect.bottom - ready_rect.top));
    fclose(ready_file);
    log_geometry(main_window, "ready-geometry");
    while ((result = GetMessageA(&message, NULL, 0, 0)) > 0) {
        TranslateMessage(&message);
        DispatchMessageA(&message);
    }
    SetEvent(finished);
    WaitForSingleObject(timer_thread, 1000);
    fprintf(events, "# complete=%u mode=%s synthetic=%u geometry_changes=%u paint=%u erase=%u dropped=%u\n",
            result == 0, mode_names[trial_mode], triggered, geometry_changes, paint_calls, erase_calls, dropped);
    fclose(events);
    CloseHandle(timer_thread);
    CloseHandle(finished);
    return result < 0 ? 4 : 0;
}
