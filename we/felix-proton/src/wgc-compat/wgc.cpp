// SPDX-License-Identifier: BSD-3-Clause
// Copyright 2026 Felix Li, with OpenAI Codex assistance.
#include "d3d.h"
#include "dmabuf/reader.h"

#include <algorithm>
#include <condition_variable>
#include <memory>

namespace wgc {
namespace {
constexpr UINT max_dimension = 4096;
constexpr DWORD interval_ms = 33;

bool fixture_title(wchar_t (&value)[128]) {
    const DWORD length = GetEnvironmentVariableW(fixture_env, value, ARRAYSIZE(value));
    return length > 0 && length < ARRAYSIZE(value);
}

unsigned portal_source(HWND window) {
    if (!GetEnvironmentVariableW(L"FELIX_WGC_AUTO_DIR", nullptr, 0)) return 0;
    const auto value = reinterpret_cast<UINT_PTR>(GetPropW(window, proxy_property));
    return value == GPU_SOURCE_WINDOW || (value >= GPU_SOURCE_FIRST_WINDOW && value <= UINT32_MAX)
        ? static_cast<unsigned>(value) : 0;
}

DWORD fixture_process(HWND window) {
    wchar_t expected[128], title[128], type[128];
    if (!GetClassNameW(window, type, ARRAYSIZE(type)) || wcscmp(type, fixture_class))
        return 0;
    if (!portal_source(window) && (!fixture_title(expected) ||
        !GetWindowTextW(window, title, ARRAYSIZE(title)) || wcscmp(title, expected)))
        return 0;
    DWORD process = 0;
    GetWindowThreadProcessId(window, &process);
    return process;
}

Size client_size(HWND window) {
    RECT rect{};
    if (GetClientRect(window, &rect))
        return {rect.right - rect.left, rect.bottom - rect.top};
    return {};
}

bool valid_size(Size size) {
    return size.Width > 0 && size.Height > 0 &&
           size.Width <= static_cast<INT32>(max_dimension) &&
           size.Height <= static_cast<INT32>(max_dimension);
}

bool monitor_source() {
    wchar_t source[16];
    const DWORD length = GetEnvironmentVariableW(L"FELIX_WGC_GPU_SOURCE", source, ARRAYSIZE(source));
    return length > 0 && length < ARRAYSIZE(source) && !wcscmp(source, L"monitor");
}

bool monitor_source_enabled() {
    return (monitor_source() || GetEnvironmentVariableW(L"FELIX_WGC_AUTO_DIR", nullptr, 0)) &&
        GetEnvironmentVariableW(L"FELIX_WGC_GPU_UNIXLIB", nullptr, 0);
}

struct MonitorEnumeration { HMONITOR handle{}; unsigned count{}; };

BOOL CALLBACK record_monitor(HMONITOR handle, HDC, RECT *, LPARAM value) {
    auto &result = *reinterpret_cast<MonitorEnumeration *>(value);
    result.handle = handle;
    ++result.count;
    return TRUE;
}

bool authorized_monitor(HMONITOR monitor, MONITORINFOEXW &info) {
    MonitorEnumeration result;
    if (!monitor || !EnumDisplayMonitors(nullptr, nullptr, record_monitor,
                                         reinterpret_cast<LPARAM>(&result)))
        return false;
    return result.count == 1 && result.handle == monitor &&
           GetMonitorInfoW(monitor, &info) && (info.dwFlags & MONITORINFOF_PRIMARY);
}

struct Target : IUnknown {
    static constexpr GUID iid{0x499b1c91,0xa10c,0x421f,{0x97,0x61,0xc0,0x47,0xaa,0xa4,0xed,0x34}};
    virtual bool live(HWND *window) = 0;
    virtual unsigned source() const = 0;
    virtual void signal_closed() = 0;
};

class CaptureItem final : public Object<CaptureItem, Item, Target> {
    const HWND window_{nullptr};
    const HMONITOR monitor_{nullptr};
    const DWORD process_{0};
    const unsigned source_{GPU_SOURCE_STATIC};
    const Size initial_;
    wchar_t monitor_name_[CCHDEVICENAME]{};
    Events<Item> closed_;
    std::atomic<bool> ended_{false};
public:
    static constexpr const wchar_t *name = item_class;
    CaptureItem(HWND window, DWORD process)
        : window_(window), process_(process), source_(portal_source(window)), initial_(client_size(window)) {}
    CaptureItem(HMONITOR monitor, const MONITORINFOEXW &info)
        : monitor_(monitor), source_(GetEnvironmentVariableW(L"FELIX_WGC_AUTO_DIR", nullptr, 0)
                                    ? GPU_SOURCE_MONITOR : GPU_SOURCE_STATIC),
          initial_{info.rcMonitor.right - info.rcMonitor.left, info.rcMonitor.bottom - info.rcMonitor.top} {
        memcpy(monitor_name_, info.szDevice, sizeof(monitor_name_));
    }
    bool live(HWND *window) override {
        if (window) *window = window_;
        if (ended_) return false;
        if (!monitor_) return portal_source(window_) == source_ && fixture_process(window_) == process_;
        MONITORINFOEXW info{};
        info.cbSize = sizeof(info);
        return GetMonitorInfoW(monitor_, &info) && !wcscmp(info.szDevice, monitor_name_);
    }
    unsigned source() const override { return source_; }
    void signal_closed() override {
        if (!ended_.exchange(true)) {
            closed_.invoke(this);
            closed_.clear();
        }
    }
    HRESULT STDMETHODCALLTYPE get_DisplayName(HSTRING *out) override {
        wchar_t label[128];
        if (!out) return E_POINTER;
        if (monitor_) return WindowsCreateString(monitor_name_, lstrlenW(monitor_name_), out);
        if (source_) {
            wchar_t current[256];
            const int length = GetWindowTextW(window_, current, ARRAYSIZE(current));
            if (length) return WindowsCreateString(current, length, out);
        }
        if (!fixture_title(label)) return E_ACCESSDENIED;
        return WindowsCreateString(label, lstrlenW(label), out);
    }
    HRESULT STDMETHODCALLTYPE get_Size(Size *out) override {
        if (!out) return E_POINTER;
        *out = initial_;
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE add_Closed(Handler<Item> *handler, EventRegistrationToken *token) override {
        return ended_ ? RO_E_CLOSED : closed_.add(handler, token);
    }
    HRESULT STDMETHODCALLTYPE remove_Closed(EventRegistrationToken token) override {
        return closed_.remove(token);
    }
};

class CaptureFrame final : public Object<CaptureFrame, Frame, Closable> {
    std::mutex mutex_;
    ComPtr<D3DSurface> surface_;
    const Size content_;
    const TimeSpan time_;
public:
    static constexpr wchar_t name[] = L"Windows.Graphics.Capture.Direct3D11CaptureFrame";
    CaptureFrame(D3DSurface *surface, Size content, TimeSpan time)
        : surface_(surface), content_(content), time_(time) {}
    HRESULT STDMETHODCALLTYPE get_Surface(D3DSurface **out) override {
        if (!out) return E_POINTER;
        *out = nullptr;
        std::lock_guard lock(mutex_);
        return surface_ ? surface_.CopyTo(out) : RO_E_CLOSED;
    }
    HRESULT STDMETHODCALLTYPE get_ContentSize(Size *out) override {
        if (!out) return E_POINTER;
        *out = content_;
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE get_SystemRelativeTime(TimeSpan *out) override {
        if (!out) return E_POINTER;
        *out = time_;
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE Close() override {
        std::lock_guard lock(mutex_);
        surface_.Reset();
        return S_OK;
    }
};

class ClientBitmap {
    HDC window_dc_, memory_dc_;
    HBITMAP bitmap_{nullptr};
    HGDIOBJ old_{nullptr};
    const HWND window_;
public:
    void *pixels = nullptr;
    explicit ClientBitmap(HWND window)
        : window_dc_(GetDC(window)), memory_dc_(window_dc_ ? CreateCompatibleDC(window_dc_) : nullptr),
          window_(window) {}
    ~ClientBitmap() {
        if (old_) SelectObject(memory_dc_, old_);
        if (bitmap_) DeleteObject(bitmap_);
        if (memory_dc_) DeleteDC(memory_dc_);
        if (window_dc_) ReleaseDC(window_, window_dc_);
    }
    bool capture(Size buffer, Size content) {
        if (!memory_dc_) return false;
        BITMAPINFO info{};
        info.bmiHeader = {sizeof(BITMAPINFOHEADER), buffer.Width, -buffer.Height, 1, 32, BI_RGB};
        bitmap_ = CreateDIBSection(memory_dc_, &info, DIB_RGB_COLORS, &pixels, nullptr, 0);
        if (!bitmap_) return false;
        old_ = SelectObject(memory_dc_, bitmap_);
        if (!old_) return false;
        const UINT cols = std::min(buffer.Width, content.Width);
        const UINT rows = std::min(buffer.Height, content.Height);
        memset(pixels, 0, static_cast<size_t>(buffer.Width) * buffer.Height * 4);
        if (!BitBlt(memory_dc_, 0, 0, cols, rows, window_dc_, 0, 0, SRCCOPY))
            return false;
        GdiFlush();
        auto *pixel = static_cast<UINT32 *>(pixels);
        for (UINT row = 0; row < rows; ++row) {
            for (UINT col = 0; col < cols; ++col)
                pixel[col] |= 0xff000000;
            pixel += buffer.Width;
        }
        return true;
    }
};

D3D11_TEXTURE2D_DESC texture_description(Size buffer) {
    D3D11_TEXTURE2D_DESC desc{};
    desc.Width = buffer.Width;
    desc.Height = buffer.Height;
    desc.MipLevels = desc.ArraySize = desc.SampleDesc.Count = 1;
    desc.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
    desc.Usage = D3D11_USAGE_DEFAULT;
    desc.BindFlags = D3D11_BIND_SHADER_RESOURCE;
    return desc;
}

ComPtr<Frame> frame_from_texture(ID3D11Texture2D *texture, Size content) {
    ComPtr<IDXGISurface> dxgi;
    if (FAILED(texture->QueryInterface(IID_PPV_ARGS(&dxgi)))) return {};
    ComPtr<D3DSurface> surface;
    surface.Attach(new (std::nothrow) Surface(dxgi.Get()));
    if (!surface) return {};
    LARGE_INTEGER now{}, clock{};
    QueryPerformanceCounter(&now);
    QueryPerformanceFrequency(&clock);
    const auto seconds = now.QuadPart / clock.QuadPart;
    const auto remainder = now.QuadPart % clock.QuadPart;
    const TimeSpan time{seconds * 10000000 + remainder * 10000000 / clock.QuadPart};
    ComPtr<Frame> frame;
    frame.Attach(new (std::nothrow) CaptureFrame(surface.Get(), content, time));
    return frame;
}

ComPtr<Frame> texture_from_window(HWND window, ID3D11Device *device, Size buffer) {
    const Size content = client_size(window);
    if (IsIconic(window) || !valid_size(content)) return {};
    ClientBitmap bitmap(window);
    if (!bitmap.capture(buffer, content)) return {};
    const auto desc = texture_description(buffer);
    const D3D11_SUBRESOURCE_DATA data{bitmap.pixels, static_cast<UINT>(buffer.Width) * 4, 0};
    ComPtr<ID3D11Texture2D> texture;
    if (FAILED(device->CreateTexture2D(&desc, &data, &texture))) return {};
    return frame_from_texture(texture.Get(), content);
}

unsigned test_rate() {
    wchar_t value[8];
    const DWORD length = GetEnvironmentVariableW(L"FELIX_WGC_FRAME_RATE", value, ARRAYSIZE(value));
    if (!length || length >= ARRAYSIZE(value)) return 0;
    wchar_t *end = nullptr;
    const unsigned rate = wcstoul(value, &end, 10);
    return *end == 0 && rate <= 120 ? rate : 0;
}

struct CaptureTiming {
    CaptureClock::time_point start = CaptureClock::now();
    UINT64 waits{}, timeouts{}, published{}, replaced{};
    UINT64 next_ns{}, target_ns{}, dxvk_ns{}, acquire_ns{}, import_ns{}, submit_ns{}, fence_ns{}, render_ns{};
    UINT64 gpu_samples{}, gdi_ns{}, schedule_ns{};

    void add(GpuWorkTiming timing, bool delivered) {
        ++waits;
        next_ns += timing.next_ns;
        if (!delivered) { ++timeouts; return; }
        target_ns += timing.target_ns;
        dxvk_ns += timing.dxvk_ns;
        acquire_ns += timing.native.acquire_ns;
        import_ns += timing.native.import_ns;
        submit_ns += timing.native.submit_ns;
        fence_ns += timing.native.fence_ns;
        render_ns += timing.native.render_ns;
        gpu_samples += timing.native.render_measured;
    }

    void report(bool gpu, bool legacy, unsigned rate, UINT64 pulled, Size size) {
        const UINT64 window_us = elapsed_ns(start)/1000;
        if (window_us < 2000000) return;
        char message[700];
        snprintf(message, sizeof(message),
                 "FELIX_WGC backend=%s legacy=%u cap=%u size=%dx%d elapsed_us=%llu published=%llu pulled=%llu"
                 " replaced=%llu waits=%llu timeouts=%llu next_us=%llu target_us=%llu dxvk_us=%llu"
                 " acquire_us=%llu import_us=%llu submit_us=%llu fence_us=%llu gpu_us=%llu gpu_samples=%llu"
                 " gdi_us=%llu schedule_us=%llu",
                 gpu ? "dmabuf" : "gdi", static_cast<unsigned>(legacy), rate, size.Width, size.Height,
                 window_us, published, pulled, replaced, waits, timeouts, next_ns/1000, target_ns/1000,
                 dxvk_ns/1000, acquire_ns/1000, import_ns/1000, submit_ns/1000, fence_ns/1000,
                 render_ns/1000, gpu_samples, gdi_ns/1000, schedule_ns/1000);
        OutputDebugStringA(message);
        *this = CaptureTiming{};
    }
};

class CapturePool final : public Object<CapturePool, FramePool, Closable> {
    // Event callbacks can close/recreate the pool on the capture thread.
    std::recursive_mutex delivery_;
    std::mutex mutex_;
    std::condition_variable wake_;
    ComPtr<ID3D11Device> device_;
    ComPtr<Frame> latest_;
    Size size_;
    UINT64 generation_{0};
    std::atomic<UINT64> pulled_{0};
    bool session_created_{false}, running_{false}, closed_{false};
    Events<FramePool> arrived_;

    static DWORD WINAPI entry(void *value) {
        auto pool = static_cast<CapturePool *>(value);
        const HRESULT result = RoInitialize(RO_INIT_MULTITHREADED);
        pool->work();
        if (SUCCEEDED(result)) RoUninitialize();
        pool->Release();
        return 0;
    }

    void work() {
        ComPtr<Target> target;
        {
            std::lock_guard lock(mutex_);
            target = target_;
        }
        if (!target) return;
        const bool trace = GetEnvironmentVariableW(L"FELIX_WGC_TIMING", nullptr, 0) != 0;
        GpuReader gpu(trace, target->source());
        const bool legacy = gpu.wanted() && GetEnvironmentVariableW(L"FELIX_WGC_LEGACY_CLOCK", nullptr, 0) != 0;
        const unsigned limit = test_rate();
        const auto period = limit ? std::chrono::nanoseconds(1000000000ull / limit)
                                  : std::chrono::milliseconds(interval_ms);
        auto deadline = CaptureClock::now();
        // In a capped trial, let the PipeWire lease arrive before the fixed
        // publication deadline. Otherwise arrival jitter can overrun the
        // companion's next pull even when the pool produces the target FPS.
        const auto lead = gpu.wanted() ? std::min(period, std::chrono::nanoseconds(36000000))
                                       : std::chrono::nanoseconds::zero();
        CaptureTiming timing;
        auto wait_until = [&](std::unique_lock<std::mutex> &lock, CaptureClock::time_point when) {
            if (when <= CaptureClock::now()) return !running_;
            const auto started = trace ? CaptureClock::now() : CaptureClock::time_point{};
            const bool stopped = wake_.wait_until(lock, when, [this] { return !running_; });
            if (trace) timing.schedule_ns += elapsed_ns(started);
            return stopped;
        };
        for (;;) {
            const auto next_tick = CaptureClock::now() + period;
            std::unique_lock lock(mutex_);
            if (!running_) break;
            if (limit && wait_until(lock, deadline - lead)) break;
            const auto generation = generation_;
            auto device = device_;
            auto size = size_;
            lock.unlock();

            HWND window = nullptr;
            const bool active = target->live(&window) && (gpu.wanted() || window);
            ComPtr<Frame> frame;
            if (active) {
                if (gpu.wanted()) {
                    ComPtr<ID3D11Texture2D> texture;
                    Size content{};
                    GpuWorkTiming work;
                    const bool ready = gpu.read(device.Get(), texture_description(size), texture, content, work);
                    if (trace) timing.add(work, ready);
                    if (ready) frame = frame_from_texture(texture.Get(), content);
                } else {
                    const auto started = trace ? CaptureClock::now() : CaptureClock::time_point{};
                    frame = texture_from_window(window, device.Get(), size);
                    if (trace) timing.gdi_ns += elapsed_ns(started);
                }
            }
            if (limit && frame && deadline > CaptureClock::now()) {
                lock.lock();
                if (wait_until(lock, deadline)) break;
                lock.unlock();
            }
            bool delivered = false;
            {
                std::lock_guard gate(delivery_);
                lock.lock();
                if (!running_) break;
                if (!active || gpu.failed()) {
                    running_ = false;
                    latest_.Reset();
                    lock.unlock();
                    target->signal_closed();
                    break;
                }
                delivered = frame && generation == generation_;
                if (delivered) {
                    if (trace) {
                        ++timing.published;
                        timing.replaced += latest_ ? 1 : 0;
                    }
                    latest_ = std::move(frame);
                }
                lock.unlock();
                if (delivered) arrived_.invoke(this);
            }
            if (trace && elapsed_ns(timing.start) >= 2000000000ull)
                timing.report(gpu.wanted(), legacy, limit, pulled_.exchange(0), size);
            if (limit) {
                if (delivered) deadline = std::max(deadline + period, CaptureClock::now() - period / 2);
                else if (!gpu.wanted()) deadline = CaptureClock::now() + period;
            } else if (!gpu.wanted() || legacy) {
                lock.lock();
                if (wait_until(lock, next_tick)) break;
            }
        }
    }

    ComPtr<Target> target_;
public:
    static constexpr const wchar_t *name = pool_class;
    CapturePool(ID3D11Device *device, Size size) : device_(device), size_(size) {}

    HRESULT start(Target *target) {
        std::lock_guard lock(mutex_);
        if (closed_) return RO_E_CLOSED;
        if (target_ || !target->live(nullptr)) return E_ILLEGAL_METHOD_CALL;
        target_ = target;
        running_ = true;
        AddRef();
        HANDLE thread = CreateThread(nullptr, 0, entry, this, 0, nullptr);
        if (!thread) {
            const DWORD error = GetLastError();
            running_ = false;
            target_.Reset();
            Release();
            return HRESULT_FROM_WIN32(error);
        }
        CloseHandle(thread);
        return S_OK;
    }

    void stop() {
        std::lock_guard gate(delivery_);
        std::lock_guard lock(mutex_);
        running_ = false;
        latest_.Reset();
        wake_.notify_all();
    }

    HRESULT STDMETHODCALLTYPE Close() override {
        std::lock_guard gate(delivery_);
        {
            std::lock_guard lock(mutex_);
            closed_ = true;
            running_ = false;
            latest_.Reset();
            device_.Reset();
            target_.Reset();
            wake_.notify_all();
        }
        arrived_.clear();
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE Recreate(D3DDevice *device, PixelFormat format, INT32 count, Size size) override {
        if (format != Bgra8 || !valid_size(size) || count <= 0) return E_INVALIDARG;
        ComPtr<ID3D11Device> inner;
        const HRESULT result = unwrap_device(device, inner.GetAddressOf());
        if (FAILED(result)) return result;
        std::lock_guard gate(delivery_);
        std::lock_guard lock(mutex_);
        if (closed_) return RO_E_CLOSED;
        device_ = std::move(inner);
        size_ = size;
        ++generation_;
        latest_.Reset();
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE TryGetNextFrame(Frame **out) override {
        if (!out) return E_POINTER;
        *out = nullptr;
        std::lock_guard lock(mutex_);
        if (closed_) return RO_E_CLOSED;
        *out = latest_.Detach();
        if (*out) ++pulled_;
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE get_DispatcherQueue(IInspectable **out) override {
        if (!out) return E_POINTER;
        *out = nullptr;
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE add_FrameArrived(Handler<FramePool> *handler, EventRegistrationToken *token) override {
        std::lock_guard gate(delivery_);
        return closed_ ? RO_E_CLOSED : arrived_.add(handler, token);
    }
    HRESULT STDMETHODCALLTYPE remove_FrameArrived(EventRegistrationToken token) override {
        return arrived_.remove(token);
    }
    HRESULT STDMETHODCALLTYPE CreateCaptureSession(Item *item, Session **out) override;
};

class CaptureSession final : public Object<CaptureSession, Session, Session2, Closable> {
    ComPtr<CapturePool> pool_;
    ComPtr<Target> item_;
    std::atomic<bool> closed_{false};
public:
    static constexpr const wchar_t *name = session_class;
    CaptureSession(CapturePool *pool, Target *item) : pool_(pool), item_(item) {}
    ~CaptureSession() { Close(); }
    HRESULT STDMETHODCALLTYPE StartCapture() override {
        if (closed_) return RO_E_CLOSED;
        const HRESULT result = pool_->start(item_.Get());
        if (closed_) pool_->stop();
        return result;
    }
    HRESULT STDMETHODCALLTYPE Close() override {
        if (!closed_.exchange(true)) pool_->stop();
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE get_IsCursorCaptureEnabled(BYTE *out) override {
        if (!out) return E_POINTER;
        if (closed_) return RO_E_CLOSED;
        *out = false;
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE put_IsCursorCaptureEnabled(BYTE value) override {
        if (closed_) return RO_E_CLOSED;
        return value ? E_NOTIMPL : S_OK;
    }
};

HRESULT CapturePool::CreateCaptureSession(Item *item, Session **out) {
    if (!out) return E_POINTER;
    *out = nullptr;
    if (!item) return E_INVALIDARG;
    ComPtr<Target> target;
    if (FAILED(item->QueryInterface(Target::iid, reinterpret_cast<void **>(target.GetAddressOf()))))
        return E_INVALIDARG;
    std::lock_guard lock(mutex_);
    if (closed_) return RO_E_CLOSED;
    if (session_created_) return E_ILLEGAL_METHOD_CALL;
    *out = new (std::nothrow) CaptureSession(this, target.Get());
    if (!*out) return E_OUTOFMEMORY;
    session_created_ = true;
    return S_OK;
}

template<class Derived, class... More>
class Factory : public Object<Derived, IActivationFactory, More...> {
public:
    HRESULT STDMETHODCALLTYPE ActivateInstance(IInspectable **out) final {
        if (!out) return E_POINTER;
        *out = nullptr;
        return E_NOTIMPL;
    }
};

class ItemFactory final : public Factory<ItemFactory, ItemInterop> {
public:
    static constexpr const wchar_t *name = item_class;
    HRESULT STDMETHODCALLTYPE CreateForWindow(HWND window, REFIID iid, void **out) override {
        if (!out) return E_POINTER;
        *out = nullptr;
        if (monitor_source()) return E_ACCESSDENIED;
        if (GetTickCount64() < gpu_retry_after.load()) return E_FAIL;
        const DWORD process = fixture_process(window);
        if (!process) return E_ACCESSDENIED;
        ComPtr<CaptureItem> item;
        item.Attach(new (std::nothrow) CaptureItem(window, process));
        return item ? item->QueryInterface(iid, out) : E_OUTOFMEMORY;
    }
    HRESULT STDMETHODCALLTYPE CreateForMonitor(HMONITOR monitor, REFIID iid, void **out) override {
        if (!out) return E_POINTER;
        *out = nullptr;
        if (!monitor_source_enabled()) return E_ACCESSDENIED;
        if (GetTickCount64() < gpu_retry_after.load()) return E_FAIL;
        MONITORINFOEXW info{};
        info.cbSize = sizeof(info);
        if (!authorized_monitor(monitor, info)) return E_INVALIDARG;
        ComPtr<CaptureItem> item;
        item.Attach(new (std::nothrow) CaptureItem(monitor, info));
        if (!item) return E_OUTOFMEMORY;
        const HRESULT result = item->QueryInterface(iid, out);
        if (SUCCEEDED(result) && GetEnvironmentVariableW(L"FELIX_WGC_TIMING", nullptr, 0))
            OutputDebugStringA("FELIX_WGC CreateForMonitor authorized");
        return result;
    }
};

class PoolFactory final : public Factory<PoolFactory, PoolStatics, PoolStatics2> {
public:
    static constexpr const wchar_t *name = pool_class;
    HRESULT STDMETHODCALLTYPE Create(D3DDevice *, PixelFormat, INT32, Size, FramePool **out) override {
        if (!out) return E_POINTER;
        *out = nullptr;
        // The dispatcher-bound overload requires a DispatcherQueue implementation.
        return E_NOTIMPL;
    }
    HRESULT STDMETHODCALLTYPE CreateFreeThreaded(D3DDevice *device, PixelFormat format, INT32 count,
                                                 Size size, FramePool **out) override {
        if (!out) return E_POINTER;
        *out = nullptr;
        if (format != Bgra8 || !valid_size(size) || count <= 0) return E_INVALIDARG;
        ComPtr<ID3D11Device> inner;
        const HRESULT result = unwrap_device(device, inner.GetAddressOf());
        if (FAILED(result)) return result;
        *out = new (std::nothrow) CapturePool(inner.Get(), size);
        return *out ? S_OK : E_OUTOFMEMORY;
    }
};

class SessionFactory final : public Factory<SessionFactory, SessionStatics> {
public:
    static constexpr const wchar_t *name = session_class;
    HRESULT STDMETHODCALLTYPE IsSupported(BYTE *out) override {
        if (!out) return E_POINTER;
        wchar_t label[128];
        *out = monitor_source_enabled() || (!monitor_source() && fixture_title(label));
        return S_OK;
    }
};
}
}

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        // Wine may release the activation factory DLL after factory lookup.
        HMODULE pinned;
        GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_PIN,
                           reinterpret_cast<LPCWSTR>(instance), &pinned);
    }
    return TRUE;
}

extern "C" HRESULT WINAPI DllGetActivationFactory(HSTRING name, IActivationFactory **out) {
    using namespace wgc;
    if (!out) return E_POINTER;
    *out = nullptr;
    const wchar_t *runtime_name = WindowsGetStringRawBuffer(name, nullptr);
    if (!wcscmp(runtime_name, item_class)) *out = new (std::nothrow) ItemFactory;
    else if (!wcscmp(runtime_name, pool_class)) *out = new (std::nothrow) PoolFactory;
    else if (!wcscmp(runtime_name, session_class)) *out = new (std::nothrow) SessionFactory;
    else return CLASS_E_CLASSNOTAVAILABLE;
    return *out ? S_OK : E_OUTOFMEMORY;
}

extern "C" HRESULT WINAPI CreateDirect3D11DeviceFromDXGIDevice(IDXGIDevice *device, IInspectable **out) {
    if (!out) return E_POINTER;
    *out = nullptr;
    if (!device) return E_INVALIDARG;
    *out = static_cast<wgc::D3DDevice *>(new (std::nothrow) wgc::Device(device));
    return *out ? S_OK : E_OUTOFMEMORY;
}

extern "C" HRESULT WINAPI CreateDirect3D11SurfaceFromDXGISurface(IDXGISurface *surface, IInspectable **out) {
    if (!out) return E_POINTER;
    *out = nullptr;
    if (!surface) return E_INVALIDARG;
    *out = static_cast<wgc::D3DSurface *>(new (std::nothrow) wgc::Surface(surface));
    return *out ? S_OK : E_OUTOFMEMORY;
}
