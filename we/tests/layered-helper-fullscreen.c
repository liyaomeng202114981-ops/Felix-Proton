/* SPDX-License-Identifier: BSD-3-Clause
 * Copyright 2026 Felix Li, with OpenAI Codex assistance.
 * Synthetic EWMH state observations for captioned owners and layered helpers.
 * No input injection, hooks, accounts or third-party applications.
 */
#define WIN32_LEAN_AND_MEAN
#define _WIN32_WINNT 0x0a00
#include <windows.h>
#include <stdio.h>
#include <wchar.h>

static LRESULT CALLBACK proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    if (msg == WM_PAINT) {
        PAINTSTRUCT paint;
        RECT rect;
        HDC dc = BeginPaint(hwnd, &paint);
        GetClientRect(hwnd, &rect);
        FillRect(dc, &rect, (HBRUSH)(COLOR_WINDOW + 1));
        EndPaint(hwnd, &paint);
        return 0;
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

int wmain(int argc, WCHAR **argv)
{
    const char *names[] = {"owned-max", "unowned", "normal-owner", "not-layered",
                          "not-transparent", "app-window", "caption-helper", "resizable-helper", "late-owned-max", "owner-restored", "overlapped-layer", "uncaptioned-owner", "late-decoration-style"};
    HWND owners[13] = {0}, helpers[13] = {0};
    MONITORINFO monitor = {.cbSize = sizeof(monitor)};
    WNDCLASSW cls = {.lpfnWndProc = proc, .hInstance = GetModuleHandleW(NULL),
                    .lpszClassName = L"SyntheticLayeredFullscreen", .hCursor = NULL};
    FILE *output;
    MSG msg;
    ULONGLONG deadline;
    BOOL hint_done = FALSE;
    if ((argc != 2 && argc != 3 && argc != 4) || !RegisterClassW(&cls) ||
        !GetMonitorInfoW(MonitorFromPoint((POINT){0, 0}, MONITOR_DEFAULTTOPRIMARY), &monitor)) return 2;
    for (unsigned i = 0; i < 13; i++) {
        DWORD exstyle = WS_EX_LAYERED | WS_EX_TRANSPARENT;
        DWORD style = (i == 12 ? 0 : WS_POPUP) | WS_CLIPSIBLINGS | WS_MINIMIZEBOX;
        owners[i] = CreateWindowExW(0, cls.lpszClassName, L"Synthetic captioned owner",
                                    i == 11 ? (WS_POPUP | WS_SYSMENU) : WS_OVERLAPPEDWINDOW,
                                    80, 100, 480, 300, NULL, NULL, cls.hInstance, NULL);
        if (!owners[i]) return 3;
        ShowWindow(owners[i], (i == 2 || i == 8) ? SW_SHOW : SW_MAXIMIZE);
        UpdateWindow(owners[i]);
        if (i == 3) exstyle &= ~WS_EX_LAYERED;
        if (i == 4) exstyle &= ~WS_EX_TRANSPARENT;
        if (i == 5) exstyle |= WS_EX_APPWINDOW;
        if (i == 6) style |= WS_CAPTION;
        if (i == 7) style |= WS_THICKFRAME;
        helpers[i] = CreateWindowExW(exstyle, cls.lpszClassName, L"Synthetic auxiliary layer",
                                    style, monitor.rcMonitor.left, monitor.rcMonitor.top,
                                    monitor.rcMonitor.right-monitor.rcMonitor.left,
                                    monitor.rcMonitor.bottom-monitor.rcMonitor.top,
                                    i == 1 ? NULL : owners[i], NULL, cls.hInstance, NULL);
        if (!helpers[i]) return 4;
        ShowWindow(helpers[i], SW_SHOW);
        if (exstyle & WS_EX_LAYERED) SetLayeredWindowAttributes(helpers[i], 0, 0, LWA_ALPHA);
        if (i == 10) SetWindowLongPtrW(helpers[i], GWL_STYLE, GetWindowLongPtrW(helpers[i], GWL_STYLE) & ~WS_POPUP);
        UpdateWindow(helpers[i]);
    }
    deadline = GetTickCount64() + 1000;
    do {
        while (PeekMessageW(&msg, NULL, 0, 0, PM_REMOVE)) { TranslateMessage(&msg); DispatchMessageW(&msg); }
        Sleep(10);
    } while (GetTickCount64() < deadline);
    /* Exercise an existing full-size helper whose owner's maximized style
     * changes after the helper's own geometry has already settled. */
    SetWindowLongPtrW(owners[8], GWL_STYLE, GetWindowLongPtrW(owners[8], GWL_STYLE) | WS_MAXIMIZE);
    ShowWindow(owners[9], SW_RESTORE);
    /* WS_OVERLAPPED acquires a caption during creation. Some decoration
     * layers shed that style after their native window is already mapped. */
    SetWindowLongPtrW(helpers[12], GWL_STYLE,
                     GetWindowLongPtrW(helpers[12], GWL_STYLE) & ~WS_CAPTION);
    deadline = GetTickCount64() + 1000;
    do {
        while (PeekMessageW(&msg, NULL, 0, 0, PM_REMOVE)) { TranslateMessage(&msg); DispatchMessageW(&msg); }
        Sleep(10);
    } while (GetTickCount64() < deadline);
    if (!(output = _wfopen(argv[1], L"wb"))) return 5;
    fputs("{\"schema\":\"synthetic-layered-fullscreen-v1\",\"windows\":[", output);
    for (unsigned i = 0; i < 13; i++) {
        ULONG_PTR owner_xid = (ULONG_PTR)GetPropW(owners[i], L"__wine_x11_whole_window");
        ULONG_PTR helper_xid = (ULONG_PTR)GetPropW(helpers[i], L"__wine_x11_whole_window");
        if (!owner_xid || !helper_xid) { fclose(output); return 6; }
        fprintf(output, "%s{\"mode\":\"%s\",\"owner_xid\":%llu,\"helper_xid\":%llu,"
                "\"owner_style\":%lu,\"helper_style\":%lu,\"helper_exstyle\":%lu}", i ? "," : "", names[i],
                (unsigned long long)owner_xid, (unsigned long long)helper_xid,
                (DWORD)GetWindowLongPtrW(owners[i], GWL_STYLE),
                (DWORD)GetWindowLongPtrW(helpers[i], GWL_STYLE),
                (DWORD)GetWindowLongPtrW(helpers[i], GWL_EXSTYLE));
    }
    fputs("]}\n", output);
    if (fclose(output)) return 7;
    deadline = GetTickCount64() + 30000;
    do {
        while (PeekMessageW(&msg, NULL, 0, 0, PM_REMOVE)) { TranslateMessage(&msg); DispatchMessageW(&msg); }
        if (argc == 4 && !hint_done && GetFileAttributesW(argv[3]) != INVALID_FILE_ATTRIBUTES) {
            WCHAR done[4096];
            FILE *signal;
            BOOL success;
            SetWindowLongPtrW(helpers[1], GWLP_HWNDPARENT, (LONG_PTR)owners[1]);
            success = GetWindow(helpers[1], GW_OWNER) == owners[1];
            success &= SetWindowPos(helpers[1], NULL, 100, 120, 600, 400,
                                    SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED);
            success &= SetWindowPos(helpers[1], NULL, monitor.rcMonitor.left, monitor.rcMonitor.top,
                                    monitor.rcMonitor.right-monitor.rcMonitor.left,
                                    monitor.rcMonitor.bottom-monitor.rcMonitor.top,
                                    SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED);
            if (swprintf(done, ARRAYSIZE(done), L"%ls.done", argv[3]) < 0) return 8;
            if (!(signal = _wfopen(done, L"wb"))) return 9;
            fputs(success ? "ok\n" : "failed\n", signal);
            if (fclose(signal)) return 10;
            hint_done = TRUE;
        }
        Sleep(10);
    } while (GetTickCount64() < deadline &&
             (argc < 3 || GetFileAttributesW(argv[2]) == INVALID_FILE_ATTRIBUTES));
    for (unsigned i = 0; i < 13; i++) { DestroyWindow(helpers[i]); DestroyWindow(owners[i]); }
    return 0;
}
