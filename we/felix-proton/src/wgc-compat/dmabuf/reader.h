// SPDX-License-Identifier: BSD-3-Clause
// Copyright 2026 Felix Li, with OpenAI Codex assistance.
#pragma once
#include "../com.h"
#include "protocol.h"
#include <cstdio>
#include <chrono>
#include <winternl.h>

namespace wgc {
struct VkInteropDevice1;
struct VkInteropSurface : IUnknown {
    static constexpr GUID iid{0x5546cf8c,0x77e7,0x4341,{0xb0,0x5d,0x8d,0x4d,0x50,0x00,0xe7,0x7d}};
    virtual HRESULT STDMETHODCALLTYPE GetDevice(IUnknown **) = 0;
    virtual HRESULT STDMETHODCALLTYPE GetVulkanImageInfo(UINT64 *, UINT32 *, void *) = 0;
};
struct VkInteropDevice1 : IUnknown {
    static constexpr GUID iid{0xe2ef5fa5,0xdc21,0x4af7,{0x90,0xc4,0xf6,0x7e,0xf6,0xa0,0x93,0x24}};
    virtual void STDMETHODCALLTYPE GetVulkanHandles(void *, void *, void *) = 0;
    virtual void STDMETHODCALLTYPE GetSubmissionQueue(void *, UINT32 *) = 0;
    virtual void STDMETHODCALLTYPE TransitionSurfaceLayout(VkInteropSurface *, const void *, UINT32, UINT32) = 0;
    virtual void STDMETHODCALLTYPE FlushRenderingCommands() = 0;
    virtual void STDMETHODCALLTYPE LockSubmissionQueue() = 0;
    virtual void STDMETHODCALLTYPE ReleaseSubmissionQueue() = 0;
    virtual void STDMETHODCALLTYPE GetSubmissionQueue1(void *, UINT32 *, UINT32 *) = 0;
};

inline std::atomic<ULONGLONG> gpu_retry_after{0};
constexpr INT memory_wine_load_unix_lib_by_name = 1002;
constexpr INT memory_wine_unload_unix_lib = 1004;

using CaptureClock = std::chrono::steady_clock;

inline UINT64 elapsed_ns(CaptureClock::time_point start) {
    return std::chrono::duration_cast<std::chrono::nanoseconds>(CaptureClock::now() - start).count();
}

struct GpuWorkTiming {
    UINT64 next_ns{}, target_ns{}, dxvk_ns{};
    gpu_timing native{};
};

class GpuReader {
    using Query = LONG (WINAPI *)(HANDLE, const void *, INT, void *, SIZE_T, SIZE_T *);
    using Call = LONG (WINAPI *)(UINT64, UINT, void *);
    Query query_{nullptr};
    Call call_{nullptr};
    UINT64 module_{0}, funcs_{0};
    gpu_call command_{};
    ComPtr<ID3D11Device> keeper_;
    bool wanted_{false}, failed_{false};

    void fail(const char *operation, LONG code) {
        char message[128];
        snprintf(message, sizeof(message), "FelixWgcGpu %s failed (%ld)", operation, code);
        OutputDebugStringA(message);
        gpu_retry_after.store(GetTickCount64() + 500);
        failed_ = true;
    }

public:
    explicit GpuReader(bool trace, unsigned source = GPU_SOURCE_STATIC) {
        command_.trace = trace;
        command_.source = source;
        wchar_t path[1024];
        const DWORD length = GetEnvironmentVariableW(L"FELIX_WGC_GPU_UNIXLIB", path, ARRAYSIZE(path));
        wanted_ = length != 0;
        if (!wanted_) return;
        if (length >= ARRAYSIZE(path)) { fail("Unix library path", E_INVALIDARG); return; }
        HMODULE ntdll = GetModuleHandleW(L"ntdll.dll");
        query_ = reinterpret_cast<Query>(GetProcAddress(ntdll, "NtQueryVirtualMemory"));
        call_ = reinterpret_cast<Call>(GetProcAddress(ntdll, "__wine_unix_call"));
        if (!query_ || !call_) { fail("Wine Unix bridge", E_NOTIMPL); return; }
        const auto bytes = static_cast<USHORT>(length * sizeof(wchar_t));
        UNICODE_STRING name{bytes, static_cast<USHORT>(bytes + sizeof(wchar_t)), path};
        UINT64 library[2]{};
        const LONG result = query_(GetCurrentProcess(), &name, memory_wine_load_unix_lib_by_name,
                                   library, sizeof(library), nullptr);
        if (result || !library[1]) { fail("load Unix library", result); return; }
        module_ = library[0];
        funcs_ = library[1];
        if (source == GPU_SOURCE_STATIC) {
            if (const LONG status = call_(funcs_, GPU_CONNECT, &command_)) fail("connect stream", status);
        }
    }
    ~GpuReader() {
        if (command_.context) call_(funcs_, GPU_CLOSE, &command_);
        if (module_) query_(GetCurrentProcess(), reinterpret_cast<const void *>(module_),
                            memory_wine_unload_unix_lib, nullptr, 0, nullptr);
    }
    bool wanted() const { return wanted_; }
    bool failed() const { return failed_; }

    bool read(ID3D11Device *device, const D3D11_TEXTURE2D_DESC &description,
              ComPtr<ID3D11Texture2D> &texture, Size &content, GpuWorkTiming &timing) {
        if (failed_) return false;
        if (!command_.context) {
            const LONG status = call_(funcs_, GPU_CONNECT, &command_);
            if (status == GPU_SOURCE_PENDING) {
                Sleep(60);
                return false;
            }
            if (status) { fail("connect source", status); return false; }
        }
        auto start = command_.trace ? CaptureClock::now() : CaptureClock::time_point{};
        const LONG next = call_(funcs_, GPU_NEXT, &command_);
        if (command_.trace) timing.next_ns = elapsed_ns(start);
        if (next == 1) return false;
        if (next) { fail("receive DMA-BUF", next); return false; }

        if (command_.trace) start = CaptureClock::now();
        ComPtr<VkInteropDevice1> interop;
        ComPtr<VkInteropSurface> image;
        HRESULT hr = device->QueryInterface(VkInteropDevice1::iid,
                                            reinterpret_cast<void **>(interop.GetAddressOf()));
        if (FAILED(hr)) { fail("DXVK device interop", hr); return false; }
        if (keeper_ && keeper_.Get() != device) { fail("D3D11 device changed", E_NOTIMPL); return false; }
        keeper_ = device;
        // DXVK submits and completes deferred initialization of shared textures
        // before returning, so it cannot clear the subsequent Vulkan write.
        auto target = description;
        target.MiscFlags = D3D11_RESOURCE_MISC_SHARED;
        target.BindFlags |= D3D11_BIND_RENDER_TARGET;
        hr = device->CreateTexture2D(&target, nullptr, &texture);
        if (FAILED(hr)) { fail("allocate target texture", hr); return false; }
        hr = texture->QueryInterface(VkInteropSurface::iid, reinterpret_cast<void **>(image.GetAddressOf()));
        if (FAILED(hr)) { fail("DXVK image interop", hr); return false; }
        hr = image->GetVulkanImageInfo(&command_.image, &command_.layout, nullptr);
        if (FAILED(hr)) { fail("DXVK image description", hr); return false; }
        void *queue = nullptr;
        interop->GetSubmissionQueue1(&queue, &command_.index, &command_.family);
        if (!queue) { fail("DXVK submission queue", E_FAIL); return false; }
        command_.width = description.Width;
        command_.height = description.Height;
        if (command_.trace) {
            timing.target_ns = elapsed_ns(start);
            start = CaptureClock::now();
        }
        interop->FlushRenderingCommands();
        interop->LockSubmissionQueue();
        if (command_.trace) timing.dxvk_ns = elapsed_ns(start);
        const LONG copied = call_(funcs_, GPU_COPY, &command_);
        interop->ReleaseSubmissionQueue();
        if (copied) { fail("GPU crop copy", copied); return false; }
        if (command_.trace) timing.native = command_.timing;
        content = {static_cast<INT32>(command_.frame.crop_width), static_cast<INT32>(command_.frame.crop_height)};
        return true;
    }
};
}
