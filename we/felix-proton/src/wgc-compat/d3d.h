// SPDX-License-Identifier: BSD-3-Clause
// Copyright 2026 Felix Li, with OpenAI Codex assistance.
#pragma once
#include "com.h"
#include <dxgi1_3.h>

namespace wgc {
class Device final : public Object<Device, D3DDevice, DxgiAccess, Closable> {
    std::mutex mutex_;
    ComPtr<IDXGIDevice> device_;
public:
    static constexpr wchar_t name[] = L"Windows.Graphics.DirectX.Direct3D11.Direct3DDevice";
    explicit Device(IDXGIDevice *device) : device_(device) {}
    HRESULT STDMETHODCALLTYPE Trim() override {
        ComPtr<IDXGIDevice3> device;
        const HRESULT result = GetInterface(IID_PPV_ARGS(&device));
        if (SUCCEEDED(result)) device->Trim();
        return result;
    }
    HRESULT STDMETHODCALLTYPE GetInterface(REFIID iid, void **out) override {
        if (!out) return E_POINTER;
        *out = nullptr;
        std::lock_guard lock(mutex_);
        return device_ ? device_->QueryInterface(iid, out) : RO_E_CLOSED;
    }
    HRESULT STDMETHODCALLTYPE Close() override {
        std::lock_guard lock(mutex_);
        device_.Reset();
        return S_OK;
    }
};

class Surface final : public Object<Surface, D3DSurface, DxgiAccess, Closable> {
    std::mutex mutex_;
    ComPtr<IDXGISurface> surface_;
public:
    static constexpr wchar_t name[] = L"Windows.Graphics.DirectX.Direct3D11.Direct3DSurface";
    explicit Surface(IDXGISurface *surface) : surface_(surface) {}
    HRESULT STDMETHODCALLTYPE get_Description(SurfaceDescription *out) override {
        if (!out) return E_POINTER;
        std::lock_guard lock(mutex_);
        if (!surface_) return RO_E_CLOSED;
        DXGI_SURFACE_DESC desc{};
        const HRESULT result = surface_->GetDesc(&desc);
        if (SUCCEEDED(result)) {
            *out = {static_cast<INT32>(desc.Width), static_cast<INT32>(desc.Height),
                    static_cast<PixelFormat>(desc.Format),
                    {static_cast<INT32>(desc.SampleDesc.Count),
                     static_cast<INT32>(desc.SampleDesc.Quality)}};
        }
        return result;
    }
    HRESULT STDMETHODCALLTYPE GetInterface(REFIID iid, void **out) override {
        if (!out) return E_POINTER;
        *out = nullptr;
        std::lock_guard lock(mutex_);
        return surface_ ? surface_->QueryInterface(iid, out) : RO_E_CLOSED;
    }
    HRESULT STDMETHODCALLTYPE Close() override {
        std::lock_guard lock(mutex_);
        surface_.Reset();
        return S_OK;
    }
};

inline HRESULT unwrap_device(D3DDevice *device, ID3D11Device **out) {
    if (!device) return E_INVALIDARG;
    ComPtr<DxgiAccess> access;
    HRESULT result = device->QueryInterface(DxgiAccess::iid,
                                            reinterpret_cast<void **>(access.GetAddressOf()));
    if (SUCCEEDED(result))
        result = access->GetInterface(__uuidof(ID3D11Device), reinterpret_cast<void **>(out));
    return result;
}
}
