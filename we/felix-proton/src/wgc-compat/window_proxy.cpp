// SPDX-License-Identifier: BSD-3-Clause
// Copyright 2026 Felix Li, with OpenAI Codex assistance.
#include "abi.h"

namespace {
LRESULT CALLBACK window_proc(HWND window, UINT message, WPARAM param, LPARAM data) {
    if (message == WM_NCHITTEST) return HTTRANSPARENT;
    if (message == WM_DESTROY) {
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(window, message, param, data);
}
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE, PWSTR, int) {
    wchar_t title[128];
    const DWORD length = GetEnvironmentVariableW(wgc::fixture_env, title, ARRAYSIZE(title));
    if (!length || length >= ARRAYSIZE(title)) return 2;

    WNDCLASSW window_class{};
    window_class.lpfnWndProc = window_proc;
    window_class.hInstance = instance;
    window_class.lpszClassName = wgc::fixture_class;
    if (!RegisterClassW(&window_class)) return 3;

    // Keep a visible Win32 capture target without painting on the desktop.
    constexpr DWORD style = WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE;
    const HWND window = CreateWindowExW(style, wgc::fixture_class, title, WS_POPUP,
                                        48, 80, 320, 200, nullptr, nullptr, instance, nullptr);
    if (!window || !SetPropW(window, wgc::proxy_property, reinterpret_cast<HANDLE>(1)) ||
        !SetLayeredWindowAttributes(window, 0, 0, LWA_ALPHA)) return 4;
    ShowWindow(window, SW_SHOWNOACTIVATE);

    MSG message{};
    BOOL result;
    while ((result = GetMessageW(&message, nullptr, 0, 0)) > 0)
        DispatchMessageW(&message);
    return result < 0 ? 5 : 0;
}
