// SPDX-License-Identifier: BSD-3-Clause
// Copyright 2026 Felix Li, with OpenAI Codex assistance.
#include "com.h"
#include <cstdio>
#include <cstdlib>

using namespace wgc;

namespace {
constexpr UINT32 red = 0xffff0000, green = 0xff00ff00, blue = 0xff0000ff;
constexpr Size original{320, 200}, resized{496, 304};

void check(bool ok, const char *what) {
    if (ok) return;
    printf("FAIL %s\n", what);
    exit(1);
}
void expect(HRESULT result, const char *what) {
    if (SUCCEEDED(result)) return;
    printf("FAIL %s: %08lx\n", what, static_cast<unsigned long>(result));
    exit(1);
}

template<class I, class T>
ComPtr<I> cast(T *object) {
    ComPtr<I> result;
    expect(object->QueryInterface(I::iid, reinterpret_cast<void **>(result.GetAddressOf())), "QueryInterface");
    return result;
}

template<class T>
ComPtr<T> factory(const wchar_t *name) {
    HSTRING id = nullptr;
    ComPtr<T> result;
    expect(WindowsCreateString(name, lstrlenW(name), &id), "WindowsCreateString");
    const HRESULT status = RoGetActivationFactory(id, T::iid, reinterpret_cast<void **>(result.GetAddressOf()));
    WindowsDeleteString(id);
    expect(status, "RoGetActivationFactory");
    return result;
}

template<class Sender>
class Counter final : public Handler<Sender> {
    std::atomic<ULONG> refs_{1};
public:
    std::atomic<unsigned> calls{0};
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID id, void **out) override {
        if (!out) return E_POINTER;
        *out = nullptr;
        if (id != IID_IUnknown && id != IID_IAgileObject) return E_NOINTERFACE;
        *out = static_cast<Handler<Sender> *>(this);
        AddRef();
        return S_OK;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return ++refs_; }
    ULONG STDMETHODCALLTYPE Release() override {
        const ULONG count = --refs_;
        if (!count) delete this;
        return count;
    }
    HRESULT STDMETHODCALLTYPE Invoke(Sender *, IInspectable *) override {
        ++calls;
        return S_OK;
    }
};

void paint(HWND window, HDC dc) {
    RECT rect{};
    GetClientRect(window, &rect);
    const bool phase = (GetTickCount64() / 180) % 2 != 0;
    SetDCBrushColor(dc, phase ? RGB(255, 0, 0) : RGB(0, 255, 0));
    const HBRUSH brush = static_cast<HBRUSH>(GetStockObject(DC_BRUSH));
    FillRect(dc, &rect, brush);
    SetDCBrushColor(dc, RGB(0, 0, 255));
    const RECT marker{0, 0, 48, 56};
    FillRect(dc, &marker, brush);
    SetBkMode(dc, TRANSPARENT);
    SetTextColor(dc, RGB(255, 255, 255));
    wchar_t text[128];
    swprintf(text, ARRAYSIZE(text), L"WGC %ld x %ld | frame %llu",
             rect.right, rect.bottom, GetTickCount64() / 80);
    TextOutW(dc, 64, 14, text, lstrlenW(text));
}

LRESULT CALLBACK window_proc(HWND window, UINT message, WPARAM param, LPARAM data) {
    switch (message) {
    case WM_TIMER:
        InvalidateRect(window, nullptr, FALSE);
        return 0;
    case WM_PRINTCLIENT:
    case WM_PRINT:
        paint(window, reinterpret_cast<HDC>(param));
        return 0;
    case WM_PAINT: {
        PAINTSTRUCT ps{};
        HDC dc = BeginPaint(window, &ps);
        paint(window, dc);
        EndPaint(window, &ps);
        return 0;
    }
    case WM_DESTROY:
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(window, message, param, data);
}

RECT outer(Size size) {
    RECT r{0, 0, size.Width, size.Height};
    AdjustWindowRectEx(&r, WS_OVERLAPPEDWINDOW, FALSE, 0);
    return r;
}

HWND fixture() {
    const HINSTANCE instance = GetModuleHandleW(nullptr);
    WNDCLASSW wc{};
    wc.lpfnWndProc = window_proc;
    wc.hInstance = instance;
    wc.lpszClassName = fixture_class;
    wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    check(RegisterClassW(&wc) != 0, "register fixture class");
    wchar_t title[128];
    DWORD length = GetEnvironmentVariableW(fixture_env, title, ARRAYSIZE(title));
    check(length > 0 && length < ARRAYSIZE(title), "fixture title supplied");
    const RECT r = outer(original);
    const auto window = CreateWindowW(fixture_class, title, WS_OVERLAPPEDWINDOW | WS_VISIBLE,
                                     48, 80, r.right-r.left, r.bottom-r.top,
                                     nullptr, nullptr, instance, nullptr);
    check(window && SetTimer(window, 1, 40, nullptr), "create fixture");
    UpdateWindow(window);
    return window;
}

void pump() {
    MSG msg{};
    while (PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE)) DispatchMessageW(&msg);
}

void read_frames(FramePool *pool, ID3D11Device *device, ID3D11DeviceContext *context, Size size,
                 const POINT *monitor_marker = nullptr) {
    const ULONGLONG deadline = GetTickCount64() + 6500;
    INT64 last_time = 0;
    bool saw_red = false, saw_green = false;
    unsigned good = 0, seen = 0;
    UINT32 corner = 0, center = 0;
    while (GetTickCount64() < deadline && !(saw_red && saw_green && good >= 4)) {
        pump();
        Sleep(12);
        ComPtr<Frame> frame;
        expect(pool->TryGetNextFrame(&frame), "TryGetNextFrame");
        if (!frame) continue;
        ++seen;
        Size reported{};
        TimeSpan time{};
        expect(frame->get_ContentSize(&reported), "get_ContentSize");
        expect(frame->get_SystemRelativeTime(&time), "get_SystemRelativeTime");
        check(time.Duration > last_time, "monotonic timestamp");
        last_time = time.Duration;
        if (reported.Width != size.Width || reported.Height != size.Height) continue;
        ComPtr<D3DSurface> surface;
        expect(frame->get_Surface(&surface), "get_Surface");
        SurfaceDescription surface_desc{};
        expect(surface->get_Description(&surface_desc), "get_Description");
        check(surface_desc.Width == size.Width && surface_desc.Height == size.Height &&
              surface_desc.Format == Bgra8 && surface_desc.MultisampleDescription.Count == 1, "surface size and format");
        ComPtr<ID3D11Texture2D> image, staging;
        ComPtr<DxgiAccess> access = cast<DxgiAccess>(surface.Get());
        expect(access->GetInterface(IID_PPV_ARGS(&image)), "surface interop texture");
        D3D11_TEXTURE2D_DESC desc{};
        image->GetDesc(&desc);
        check(desc.Width == static_cast<UINT>(size.Width) && desc.Height == static_cast<UINT>(size.Height) &&
              desc.Format == DXGI_FORMAT_B8G8R8A8_UNORM, "texture size and format");
        desc.Usage = D3D11_USAGE_STAGING;
        desc.BindFlags = 0;
        desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
        expect(device->CreateTexture2D(&desc, nullptr, &staging), "create staging texture");
        context->CopyResource(staging.Get(), image.Get());
        D3D11_MAPPED_SUBRESOURCE mapping{};
        expect(context->Map(staging.Get(), 0, D3D11_MAP_READ, 0, &mapping), "map staging");
        const auto bytes = static_cast<const unsigned char *>(mapping.pData);
        const auto sample = [&](int x, int y) {
            return reinterpret_cast<const UINT32 *>(bytes + mapping.RowPitch * y)[x];
        };
        if (monitor_marker) {
            corner = sample(monitor_marker->x + 16, monitor_marker->y + 16);
            center = sample(monitor_marker->x + original.Width / 2,
                            monitor_marker->y + original.Height / 2);
        } else {
            corner = sample(16, 16);
            center = sample(size.Width / 2, size.Height / 2);
        }
        context->Unmap(staging.Get(), 0);
        expect(cast<Closable>(frame.Get())->Close(), "close frame");
        check(frame->get_Surface(&surface) == RO_E_CLOSED, "closed frame state");
        if (corner != blue) continue;
        saw_red |= center == red;
        saw_green |= center == green;
        if (center == red || center == green) ++good;
    }
    printf("WGC %dx%d frames=%u valid=%u red=%d green=%d sample=%08x,%08x\n",
           size.Width, size.Height, seen, good, saw_red, saw_green, corner, center);
    check(saw_red && saw_green && good >= 4, "animated authorized pixels in D3D11 texture");
}

UINT64 cpu_time() {
    FILETIME created{}, exited{}, kernel{}, user{};
    check(GetProcessTimes(GetCurrentProcess(), &created, &exited, &kernel, &user), "process CPU time");
    const auto ticks = [](FILETIME time) {
        return (static_cast<UINT64>(time.dwHighDateTime) << 32) | time.dwLowDateTime;
    };
    return ticks(kernel) + ticks(user);
}

void benchmark(FramePool *pool, ID3D11DeviceContext *context, ID3D11Device *device,
               Size size, unsigned seconds) {
    const auto warm = GetTickCount64() + 2500;
    while (GetTickCount64() < warm) {
        pump();
        ComPtr<Frame> frame;
        expect(pool->TryGetNextFrame(&frame), "warmup TryGetNextFrame");
        Sleep(3);
    }

    D3D11_TEXTURE2D_DESC description{};
    description.Width = size.Width;
    description.Height = size.Height;
    description.ArraySize = description.MipLevels = description.SampleDesc.Count = 1;
    description.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
    ComPtr<ID3D11Texture2D> sink;
    expect(device->CreateTexture2D(&description, nullptr, &sink), "create simulated preview texture");
    const UINT64 cpu_start = cpu_time();
    const auto start = GetTickCount64();
    unsigned frames = 0, wrong_size = 0;
    while (GetTickCount64() - start < seconds * 1000) {
        pump();
        ComPtr<Frame> frame;
        expect(pool->TryGetNextFrame(&frame), "benchmark TryGetNextFrame");
        if (frame) {
            Size content{};
            expect(frame->get_ContentSize(&content), "benchmark content size");
            if (size.Width != content.Width || size.Height != content.Height) {
                ++wrong_size;
            } else {
                ComPtr<D3DSurface> surface;
                ComPtr<ID3D11Texture2D> texture;
                expect(frame->get_Surface(&surface), "benchmark surface");
                expect(cast<DxgiAccess>(surface.Get())->GetInterface(IID_PPV_ARGS(&texture)), "benchmark texture");
                context->CopyResource(sink.Get(), texture.Get());
                ++frames;
            }
        }
        Sleep(3);
    }
    context->Flush();
    const double elapsed = (GetTickCount64() - start) / 1000.0;
    const double cpu = (cpu_time() - cpu_start) / 10000.0;
    printf("BENCH %dx%d wall=%.3f frames=%u wrong_size=%u fps=%.2f cpu_ms=%.2f cpu_ms_per_frame=%.3f\n",
           size.Width, size.Height, elapsed, frames, wrong_size, frames / elapsed, cpu, frames ? cpu / frames : 0.0);
    check(frames > 0 && !wrong_size, "benchmark received requested texture size");
}

void verify(HWND window, unsigned bench_seconds, HMONITOR monitor = nullptr) {
    Size expected = bench_seconds ? Size{960, 540} : original;
    POINT marker{};
    if (monitor) {
        MONITORINFO info{};
        info.cbSize = sizeof(info);
        check(GetMonitorInfoW(monitor, &info), "read primary monitor bounds");
        expected = {info.rcMonitor.right - info.rcMonitor.left, info.rcMonitor.bottom - info.rcMonitor.top};
        check(ClientToScreen(window, &marker), "locate the monitor test marker");
        marker.x -= info.rcMonitor.left;
        marker.y -= info.rcMonitor.top;
        check(marker.x >= 0 && marker.y >= 0 && marker.x + original.Width <= expected.Width &&
              marker.y + original.Height <= expected.Height, "monitor test marker is on the selected display");
    }
    if (bench_seconds) {
        const RECT r = outer(expected);
        check(SetWindowPos(window, nullptr, 0, 0, r.right-r.left, r.bottom-r.top,
                           SWP_NOMOVE | SWP_NOZORDER), "resize benchmark fixture");
        const auto deadline = GetTickCount64() + 2500;
        RECT actual{};
        do {
            pump();
            Sleep(10);
            GetClientRect(window, &actual);
        } while ((actual.right != expected.Width || actual.bottom != expected.Height) &&
                 GetTickCount64() < deadline);
    }
    expect(RoInitialize(RO_INIT_MULTITHREADED), "RoInitialize");
    ComPtr<ID3D11Device> d3d;
    ComPtr<ID3D11DeviceContext> context;
    D3D_FEATURE_LEVEL feature{};
    expect(D3D11CreateDevice(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, D3D11_CREATE_DEVICE_BGRA_SUPPORT,
                             nullptr, 0, D3D11_SDK_VERSION, &d3d, &feature, &context), "D3D11CreateDevice");
    ComPtr<IDXGIDevice> dxgi;
    expect(d3d.As(&dxgi), "DXGI device");
    const HMODULE d3d_lib = GetModuleHandleW(L"d3d11.dll");
    const auto bridge = reinterpret_cast<CreateDeviceBridge>(
        GetProcAddress(d3d_lib, "CreateDirect3D11DeviceFromDXGIDevice"));
    const auto surface_bridge = reinterpret_cast<CreateSurfaceBridge>(
        GetProcAddress(d3d_lib, "CreateDirect3D11SurfaceFromDXGISurface"));
    check(bridge && surface_bridge, "D3D11 WinRT exports");
    ComPtr<IInspectable> generic;
    check(bridge(nullptr, &generic) == E_INVALIDARG, "reject null DXGI device");
    check(surface_bridge(nullptr, &generic) == E_INVALIDARG, "reject null DXGI surface");
    expect(bridge(dxgi.Get(), &generic), "CreateDirect3D11DeviceFromDXGIDevice");
    auto device = cast<D3DDevice>(generic.Get());
    auto statics = factory<SessionStatics>(session_class);
    BYTE supported = 0;
    expect(statics->IsSupported(&supported), "IsSupported");
    check(supported, "explicitly enabled prototype");
    const auto interop = factory<ItemInterop>(item_class);
    ComPtr<Item> item;
    check(interop->CreateForWindow(GetDesktopWindow(), Item::iid,
          reinterpret_cast<void **>(item.GetAddressOf())) == E_ACCESSDENIED, "reject unrelated window");
    if (monitor) {
        check(interop->CreateForMonitor(nullptr, Item::iid,
              reinterpret_cast<void **>(item.GetAddressOf())) == E_INVALIDARG, "reject null monitor");
        expect(interop->CreateForMonitor(monitor, Item::iid, reinterpret_cast<void **>(item.GetAddressOf())),
               "CreateForMonitor");
    } else {
        check(interop->CreateForMonitor(MonitorFromWindow(window, MONITOR_DEFAULTTOPRIMARY), Item::iid,
              reinterpret_cast<void **>(item.GetAddressOf())) == E_ACCESSDENIED, "reject unrequested monitor");
        expect(interop->CreateForWindow(window, Item::iid, reinterpret_cast<void **>(item.GetAddressOf())),
               "CreateForWindow");
    }
    Size initial{};
    expect(item->get_Size(&initial), "item size");
    check(initial.Width == expected.Width && initial.Height == expected.Height, "initial item bounds");
    ComPtr<Counter<Item>> closed;
    closed.Attach(new Counter<Item>);
    EventRegistrationToken close_token{};
    expect(item->add_Closed(closed.Get(), &close_token), "subscribe Closed");

    const auto pools = factory<PoolStatics2>(pool_class);
    ComPtr<FramePool> pool;
    expect(pools->CreateFreeThreaded(device.Get(), Bgra8, 2, initial, &pool), "CreateFreeThreaded");
    ComPtr<Counter<FramePool>> arrived;
    arrived.Attach(new Counter<FramePool>);
    EventRegistrationToken frame_token{};
    expect(pool->add_FrameArrived(arrived.Get(), &frame_token), "subscribe FrameArrived");
    ComPtr<Session> session;
    expect(pool->CreateCaptureSession(item.Get(), &session), "CreateCaptureSession");
    expect(session->StartCapture(), "StartCapture");
    if (bench_seconds) {
        benchmark(pool.Get(), context.Get(), d3d.Get(), expected, bench_seconds);
        DestroyWindow(window);
        expect(cast<Closable>(session.Get())->Close(), "close benchmark session");
        expect(cast<Closable>(pool.Get())->Close(), "close benchmark pool");
        RoUninitialize();
        return;
    }
    if (monitor) {
        read_frames(pool.Get(), d3d.Get(), context.Get(), expected, &marker);
        expect(cast<Closable>(session.Get())->Close(), "close monitor session");
        expect(cast<Closable>(pool.Get())->Close(), "close monitor pool");
        const unsigned delivered = arrived->calls;
        Sleep(180);
        ComPtr<Frame> frame;
        check(pool->TryGetNextFrame(&frame) == RO_E_CLOSED && !frame, "monitor pool stops publishing");
        check(arrived->calls == delivered, "no callbacks after monitor capture closes");
        printf("MONITOR FrameArrived=%u closed=1\n", delivered);
        DestroyWindow(window);
        RoUninitialize();
        return;
    }
    read_frames(pool.Get(), d3d.Get(), context.Get(), original);
    const RECT r = outer(resized);
    check(SetWindowPos(window, nullptr, 0, 0, r.right-r.left, r.bottom-r.top,
                       SWP_NOMOVE | SWP_NOZORDER), "resize fixture");
    pump();
    if (GetEnvironmentVariableW(L"FELIX_WGC_GPU_UNIXLIB", nullptr, 0)) {
        HANDLE trigger = CreateFileW(L"C:\\felix-wgc-resize", GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, 0, nullptr);
        check(trigger != INVALID_HANDLE_VALUE, "trigger Wayland resize");
        CloseHandle(trigger);
    }
    expect(pool->Recreate(device.Get(), Bgra8, 2, resized), "recreate pool");
    read_frames(pool.Get(), d3d.Get(), context.Get(), resized);
    check(DestroyWindow(window), "destroy fixture");
    const auto deadline = GetTickCount64() + 2000;
    while (!closed->calls && GetTickCount64() < deadline) Sleep(10);
    check(closed->calls == 1, "Closed exactly once");
    const unsigned delivered = arrived->calls;
    Sleep(180);
    check(arrived->calls == delivered, "no frame callbacks after window closure");
    ComPtr<Frame> frame;
    expect(pool->TryGetNextFrame(&frame), "closed-target pool drain");
    check(!frame, "no stale frames after target closure");
    expect(cast<Closable>(session.Get())->Close(), "close session");
    expect(cast<Closable>(pool.Get())->Close(), "close pool");
    check(pool->TryGetNextFrame(&frame) == RO_E_CLOSED, "closed pool rejects reads");
    printf("WGC Close=1 FrameArrived=%u queued=0 stopped=1 selective=1\n", delivered);
    RoUninitialize();
}
}

int wmain(int argc, wchar_t **argv) {
    const bool only = argc == 2 && !wcscmp(argv[1], L"--fixture-only");
    if (!only && !_wfreopen(L"C:\\felix-wgc-probe.log", L"w", stdout)) return 2;
    setvbuf(stdout, nullptr, _IONBF, 0);
    if (argc == 2 && !wcscmp(argv[1], L"--monitor")) {
        if (HWND console = GetConsoleWindow()) ShowWindow(console, SW_HIDE);
        HMONITOR monitor = MonitorFromPoint({0, 0}, MONITOR_DEFAULTTOPRIMARY);
        check(monitor != nullptr, "find active monitor");
        HWND marker = fixture();
        check(SetWindowPos(marker, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE),
              "raise the monitor test marker");
        pump();
        verify(marker, 0, monitor);
        return 0;
    }
    const HWND window = fixture();
    if (only) {
        MSG message{};
        while (GetMessageW(&message, nullptr, 0, 0) > 0) DispatchMessageW(&message);
    } else {
        const unsigned seconds = argc == 3 && !wcscmp(argv[1], L"--bench")
            ? static_cast<unsigned>(wcstoul(argv[2], nullptr, 10)) : 0;
        check(seconds <= 60, "benchmark duration");
        verify(window, seconds);
    }
    return 0;
}
