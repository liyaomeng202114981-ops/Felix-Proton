// SPDX-License-Identifier: BSD-3-Clause
// Copyright 2026 Felix Li, with OpenAI Codex assistance.
// Handle the companion window picker through Windows UI Automation.
#include <windows.h>
#include <shellapi.h>
#include <uiautomationclient.h>
#include <cstdio>
#include <cwchar>
#include <algorithm>
#include <string>
#include <vector>
#include "abi.h"
#include "dmabuf/protocol.h"

namespace {
constexpr wchar_t title[] = L"直播伴侣";
constexpr wchar_t picker_label[] = L"选择窗口（请保持窗口打开并放于桌面上）";
DWORD target_pid{};
IUIAutomation *automation{};
IUIAutomationCondition *all_elements{};
FILE *audit{};

struct Proxy {
    HWND window{};
    std::wstring directory;
};

void report(const char *message) {
    if (audit) std::fprintf(audit, "%s\n", message);
}

BOOL CALLBACK find_target(HWND window, LPARAM) {
    wchar_t name[64]{}, cls[64]{};
    RECT rect{};
    if (!IsWindowVisible(window) || !GetWindowRect(window, &rect) ||
        rect.right - rect.left < 700 || rect.bottom - rect.top < 400 ||
        !GetWindowTextW(window, name, ARRAYSIZE(name)) || wcscmp(name, title) ||
        !GetClassNameW(window, cls, ARRAYSIZE(cls)) || wcsncmp(cls, L"Chrome_WidgetWin_", 17))
        return TRUE;
    GetWindowThreadProcessId(window, &target_pid);
    return FALSE;
}

bool belongs(HWND window) {
    DWORD pid{};
    return window && GetWindowThreadProcessId(window, &pid) && pid == target_pid;
}

struct Picker {
    HWND window{};
    RECT input{}, option{};
    std::wstring label;
};

BOOL CALLBACK find_picker(HWND window, LPARAM parameter) {
    if (!belongs(window) || !IsWindowVisible(window)) return TRUE;
    RECT bounds{};
    GetWindowRect(window, &bounds);
    if (bounds.right - bounds.left > 650) return TRUE;
    IUIAutomationElement *root{};
    IUIAutomationElementArray *items{};
    if (FAILED(automation->ElementFromHandle(window, &root)) || !root) return TRUE;
    const auto status = root->FindAll(TreeScope_Descendants, all_elements, &items);
    root->Release();
    if (FAILED(status) || !items) return TRUE;
    bool is_picker = false;
    auto &picker = *reinterpret_cast<Picker *>(parameter);
    Picker found{};
    found.label = picker.label;
    int count{};
    items->get_Length(&count);
    for (int i = 0; i < count && i < 400; ++i) {
        IUIAutomationElement *item{};
        if (FAILED(items->GetElement(i, &item)) || !item) continue;
        BSTR name{};
        CONTROLTYPEID type{};
        RECT box{};
        item->get_CurrentName(&name);
        item->get_CurrentControlType(&type);
        item->get_CurrentBoundingRectangle(&box);
        if (name && !wcscmp(name, picker_label)) is_picker = true;
        if (type == UIA_ComboBoxControlTypeId ||
            (name && !wcscmp(name, L"请选择") && !found.input.right))
            found.input = box;
        if (name && !found.label.empty() && !wcscmp(name, found.label.c_str()) &&
            box.top > found.input.bottom &&
            box.right > box.left && box.bottom > box.top)
            found.option = box;
        SysFreeString(name);
        item->Release();
    }
    items->Release();
    if (!is_picker) return TRUE;
    found.window = window;
    picker = found;
    return FALSE;
}

bool click_picker(HWND window, RECT box) {
    if (!belongs(window) || box.right <= box.left || box.bottom <= box.top) return false;
    HWND renderer{};
    EnumChildWindows(window, [](HWND child, LPARAM result) -> BOOL {
        wchar_t cls[64]{};
        GetClassNameW(child, cls, ARRAYSIZE(cls));
        if (!IsWindowVisible(child) || wcscmp(cls, L"Chrome_RenderWidgetHostHWND"))
            return TRUE;
        *reinterpret_cast<HWND *>(result) = child;
        return FALSE;
    }, reinterpret_cast<LPARAM>(&renderer));
    POINT point{(box.left + box.right) / 2, (box.top + box.bottom) / 2};
    RECT client{};
    if (!belongs(renderer) || !ScreenToClient(renderer, &point) ||
        !GetClientRect(renderer, &client) || !PtInRect(&client, point))
        return false;
    const auto position = MAKELPARAM(point.x, point.y);
    return PostMessageW(renderer, WM_MOUSEMOVE, 0, position) &&
           PostMessageW(renderer, WM_LBUTTONDOWN, MK_LBUTTON, position) &&
           PostMessageW(renderer, WM_LBUTTONUP, 0, position);
}

std::wstring read_title(const std::wstring &path) {
    FILE *file = _wfopen(path.c_str(), L"rb");
    if (!file) return L"Ubuntu 窗口";
    char text[1024];
    size_t length = std::fread(text, 1, sizeof(text), file);
    std::fclose(file);
    while (length && (text[length - 1] == '\n' || text[length - 1] == '\r')) --length;
    wchar_t wide[256];
    const int count = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text,
                                          static_cast<int>(length), wide, ARRAYSIZE(wide));
    return count ? std::wstring(wide, count) : L"Ubuntu 窗口";
}

LRESULT CALLBACK proxy_proc(HWND window, UINT message, WPARAM param, LPARAM data) {
    if (message == WM_NCHITTEST) return HTTRANSPARENT;
    return DefWindowProcW(window, message, param, data);
}

HWND prepare_proxy(HINSTANCE instance, const std::wstring &directory, DWORD token,
                   const std::wstring &prefix, std::wstring &label) {
    const auto answer = directory + L"\\ready";
    const auto title_file = directory + L"\\source-title";
    FILE *file = _wfopen(answer.c_str(), L"r");
    if (!file) return nullptr;
    LONG width{}, height{};
    const int read = std::fscanf(file, "%ld %ld", &width, &height);
    std::fclose(file);
    if (read != 2 || width < 1 || width > 8192 || height < 1 || height > 8192)
        return nullptr;
    const auto title = read_title(title_file);
    constexpr DWORD style = WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE;
    const HWND proxy = CreateWindowExW(style, wgc::fixture_class, title.c_str(), WS_POPUP,
                                       48, 80, width, height, nullptr, nullptr, instance, nullptr);
    if (!proxy) return nullptr;
    if (!SetPropW(proxy, wgc::proxy_property, reinterpret_cast<HANDLE>(static_cast<UINT_PTR>(token))) ||
        !SetLayeredWindowAttributes(proxy, 0, 0, LWA_ALPHA)) {
        DestroyWindow(proxy);
        return nullptr;
    }
    ShowWindow(proxy, SW_SHOWNOACTIVATE);
    label = prefix + title;
    DeleteFileW(title_file.c_str());
    DeleteFileW(answer.c_str());
    report("window proxy title and size ready for the authorized source");
    return proxy;
}

bool exists(const std::wstring &path) {
    return GetFileAttributesW(path.c_str()) != INVALID_FILE_ATTRIBUTES;
}

void cancel(const std::wstring &directory) {
    const auto flag = directory + L"\\cancel";
    FILE *file = _wfopen(flag.c_str(), L"wb");
    if (file) std::fclose(file);
}

bool request(const std::wstring &base, DWORD token) {
    const auto destination = base + L"\\request";
    const auto temporary = base + L"\\request.new";
    if (exists(destination)) return false;
    FILE *file = _wfopen(temporary.c_str(), L"wb");
    if (!file) return false;
    std::fprintf(file, "window %lu\n", static_cast<unsigned long>(token));
    if (std::fclose(file) == 0 && MoveFileExW(temporary.c_str(), destination.c_str(), 0)) return true;
    DeleteFileW(temporary.c_str());
    return false;
}
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE, PWSTR, int) {
    int argc = 0;
    wchar_t **argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (!argv) return 2;
    const std::wstring base = argc == 2 ? argv[1] : L"";
    LocalFree(argv);
    if (base.empty() || FAILED(CoInitializeEx(nullptr, COINIT_MULTITHREADED))) return 2;
    WNDCLASSW window_class{};
    window_class.lpfnWndProc = proxy_proc;
    window_class.hInstance = instance;
    window_class.lpszClassName = wgc::fixture_class;
    wchar_t image[MAX_PATH]{};
    const DWORD length = GetModuleFileNameW(nullptr, image, ARRAYSIZE(image));
    if (!RegisterClassW(&window_class) || !length || length >= ARRAYSIZE(image)) return 2;
    const wchar_t *filename = wcsrchr(image, L'\\');
    const std::wstring prefix = std::wstring(filename ? filename + 1 : image) + L" ";
    audit = _wfopen((base + L"\\actions.log").c_str(), L"a");
    if (audit) setvbuf(audit, nullptr, _IONBF, 0);
    EnumWindows(find_target, 0);
    report(target_pid ? "companion window found" : "companion window unavailable");
    if (!target_pid) return 3;
    const auto result = CoCreateInstance(CLSID_CUIAutomation, nullptr, CLSCTX_INPROC_SERVER,
                                         IID_IUIAutomation, reinterpret_cast<void **>(&automation));
    if (FAILED(result) || !automation) {
        report("Windows automation unavailable");
        return 4;
    }
    if (FAILED(automation->CreateTrueCondition(&all_elements)) || !all_elements) {
        report("accessibility tree condition unavailable");
        return 5;
    }
    report("window chooser observer ready");
    const auto captures = base + L"\\window";
    if (!CreateDirectoryW(captures.c_str(), nullptr) && GetLastError() != ERROR_ALREADY_EXISTS) return 6;
    MSG message{};
    std::vector<Proxy> active;
    HWND dialog{};
    HWND last_picker{};
    HWND proxy{};
    bool expanded = false, submitted = false;
    ULONGLONG finish_by{};
    DWORD token = GetTickCount();
    std::wstring directory;
    std::wstring label;

    auto finish = [&](bool added) {
        if (proxy && !added) DestroyWindow(proxy);
        if (added) active.push_back({proxy, directory});
        else if (exists(directory + L"\\closed")) {
            DeleteFileW((directory + L"\\closed").c_str());
            RemoveDirectoryW(directory.c_str());
        } else {
            cancel(directory);
            active.push_back({nullptr, directory});
        }
        for (const auto &source : active)
            if (source.window) ShowWindow(source.window, SW_SHOWNOACTIVATE);
        if (belongs(dialog)) PostMessageW(dialog, WM_CLOSE, 0, 0);
        dialog = nullptr;
        proxy = nullptr;
        finish_by = 0;
        expanded = submitted = false;
        label.clear();
    };

    const UINT_PTR timer = SetTimer(nullptr, 0, 220, nullptr);
    if (!timer) return 6;
    while (GetMessageW(&message, nullptr, 0, 0) > 0) {
        if (message.message != WM_TIMER || message.wParam != timer) {
            DispatchMessageW(&message);
            continue;
        }
        active.erase(std::remove_if(active.begin(), active.end(), [](const Proxy &source) {
            const auto flag = source.directory + L"\\closed";
            if (!exists(flag)) return false;
            if (source.window) DestroyWindow(source.window);
            DeleteFileW(flag.c_str());
            RemoveDirectoryW(source.directory.c_str());
            return true;
        }), active.end());
        if (dialog && !belongs(dialog)) {
            finish(false);
            last_picker = nullptr;
        }
        if (dialog && exists(directory + L"\\closed")) {
            finish(false);
            continue;
        }
        if (dialog && !proxy) {
            proxy = prepare_proxy(instance, directory, token, prefix, label);
            if (proxy) {
                for (const auto &source : active)
                    if (source.window) ShowWindow(source.window, SW_HIDE);
                ShowWindowAsync(dialog, SW_SHOWNOACTIVATE);
                finish_by = GetTickCount64() + 10000;
            } else if (GetTickCount64() >= finish_by) {
                report("Ubuntu window request did not complete");
                finish(false);
            }
            continue;
        }
        Picker picker{};
        picker.label = label;
        EnumWindows(find_picker, reinterpret_cast<LPARAM>(&picker));
        if (!dialog && picker.window != last_picker) {
            last_picker = picker.window;
            if (last_picker) {
                if (++token < GPU_SOURCE_FIRST_WINDOW) token = GPU_SOURCE_FIRST_WINDOW;
                directory = captures + L"\\" + std::to_wstring(token);
                if (CreateDirectoryW(directory.c_str(), nullptr)) {
                    if (!request(base, token)) {
                        RemoveDirectoryW(directory.c_str());
                        PostMessageW(last_picker, WM_CLOSE, 0, 0);
                        continue;
                    }
                    dialog = last_picker;
                    finish_by = GetTickCount64() + 265000;
                    ShowWindowAsync(dialog, SW_HIDE);
                    report("Ubuntu window chooser requested");
                }
            }
        }
        if (!dialog || !proxy) continue;
        if (GetTickCount64() >= finish_by) {
            report("companion window selector did not complete");
            finish(false);
        } else if (submitted) {
            if (exists(directory + L"\\first-lease")) {
                FILE *material = _wfopen((directory + L"\\material").c_str(), L"w");
                if (material) {
                    std::fprintf(material, "%llu\n", static_cast<unsigned long long>(
                        reinterpret_cast<UINT_PTR>(proxy)));
                    std::fclose(material);
                }
                report("authorized window frame confirmed and companion selector closed");
                finish(true);
            }
        } else if (picker.window == dialog && click_picker(dialog, picker.option)) {
            report("authorized window selected in companion");
            submitted = true;
        } else if (picker.window == dialog && !expanded) {
            expanded = click_picker(dialog, picker.input);
        }
    }
    if (timer) KillTimer(nullptr, timer);
    all_elements->Release();
    automation->Release();
    CoUninitialize();
    return 0;
}
