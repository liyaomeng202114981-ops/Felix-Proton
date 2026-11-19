// SPDX-License-Identifier: BSD-3-Clause
// Copyright 2026 Felix Li, with OpenAI Codex assistance.
#pragma once
#include <windows.h>
#include <d3d11.h>
#include <inspectable.h>
#include <roapi.h>
#include <winstring.h>
#include <eventtoken.h>

// Public WinRT ABI. The pinned MinGW SDK lacks most capture interfaces.
// Runtime-class pointer parameters use the class's default interface.
#ifndef RO_E_CLOSED
#define RO_E_CLOSED _HRESULT_TYPEDEF_(0x80000013)
#endif
#ifndef E_ILLEGAL_METHOD_CALL
#define E_ILLEGAL_METHOD_CALL _HRESULT_TYPEDEF_(0x8000000e)
#endif

namespace wgc {
#define WGC_INTERFACE(Name, Base, ...) \
    struct Name : Base { static constexpr GUID iid{__VA_ARGS__};
#define WGC_METHOD(Name, ...) virtual HRESULT STDMETHODCALLTYPE Name(__VA_ARGS__) = 0

struct Size { INT32 Width, Height; };
struct TimeSpan { INT64 Duration; };
enum PixelFormat : INT32 { Bgra8 = DXGI_FORMAT_B8G8R8A8_UNORM };
struct SurfaceDescription {
    INT32 Width, Height;
    PixelFormat Format;
    struct { INT32 Count, Quality; } MultisampleDescription;
};

WGC_INTERFACE(Closable, IInspectable, 0x30d5a829,0x7fa4,0x4026,{0x83,0xbb,0xd7,0x5b,0xae,0x4e,0xa9,0x9e})
    WGC_METHOD(Close);
};
WGC_INTERFACE(D3DDevice, IInspectable, 0xa37624ab,0x8d5f,0x4650,{0x9d,0x3e,0x9e,0xae,0x3d,0x9b,0xc6,0x70})
    WGC_METHOD(Trim);
};
WGC_INTERFACE(D3DSurface, IInspectable, 0x0bf4a146,0x13c1,0x4694,{0xbe,0xe3,0x7a,0xbf,0x15,0xea,0xf5,0x86})
    WGC_METHOD(get_Description, SurfaceDescription *);
};
WGC_INTERFACE(DxgiAccess, IUnknown, 0xa9b3d012,0x3df2,0x4ee3,{0xb8,0xd1,0x86,0x95,0xf4,0x57,0xd3,0xc1})
    WGC_METHOD(GetInterface, REFIID, void **);
};
struct FramePool;
struct Item;
struct Session;
template<typename Sender> struct Handler : IUnknown {
    WGC_METHOD(Invoke, Sender *, IInspectable *);
};

WGC_INTERFACE(Item, IInspectable, 0x79c3f95b,0x31f7,0x4ec2,{0xa4,0x64,0x63,0x2e,0xf5,0xd3,0x07,0x60})
    WGC_METHOD(get_DisplayName, HSTRING *);
    WGC_METHOD(get_Size, Size *);
    WGC_METHOD(add_Closed, Handler<Item> *, EventRegistrationToken *);
    WGC_METHOD(remove_Closed, EventRegistrationToken);
};
WGC_INTERFACE(ItemInterop, IUnknown, 0x3628e81b,0x3cac,0x4c60,{0xb7,0xf4,0x23,0xce,0x0e,0x0c,0x33,0x56})
    WGC_METHOD(CreateForWindow, HWND, REFIID, void **);
    WGC_METHOD(CreateForMonitor, HMONITOR, REFIID, void **);
};
WGC_INTERFACE(Frame, IInspectable, 0xfa50c623,0x38da,0x4b32,{0xac,0xf3,0xfa,0x97,0x34,0xad,0x80,0x0e})
    WGC_METHOD(get_Surface, D3DSurface **);
    WGC_METHOD(get_SystemRelativeTime, TimeSpan *);
    WGC_METHOD(get_ContentSize, Size *);
};
WGC_INTERFACE(FramePool, IInspectable, 0x24eb6d22,0x1975,0x422e,{0x82,0xe7,0x78,0x0d,0xbd,0x8d,0xdf,0x24})
    WGC_METHOD(Recreate, D3DDevice *, PixelFormat, INT32, Size);
    WGC_METHOD(TryGetNextFrame, Frame **);
    WGC_METHOD(add_FrameArrived, Handler<FramePool> *, EventRegistrationToken *);
    WGC_METHOD(remove_FrameArrived, EventRegistrationToken);
    WGC_METHOD(CreateCaptureSession, Item *, Session **);
    WGC_METHOD(get_DispatcherQueue, IInspectable **);
};
WGC_INTERFACE(PoolStatics, IInspectable, 0x7784056a,0x67aa,0x4d53,{0xae,0x54,0x10,0x88,0xd5,0xa8,0xca,0x21})
    WGC_METHOD(Create, D3DDevice *, PixelFormat, INT32, Size, FramePool **);
};
WGC_INTERFACE(PoolStatics2, IInspectable, 0x589b103f,0x6bbc,0x5df5,{0xa9,0x91,0x02,0xe2,0x8b,0x3b,0x66,0xd5})
    WGC_METHOD(CreateFreeThreaded, D3DDevice *, PixelFormat, INT32, Size, FramePool **);
};
WGC_INTERFACE(Session, IInspectable, 0x814e42a9,0xf70f,0x4ad7,{0x93,0x9b,0xfd,0xdc,0xc6,0xeb,0x88,0x0d})
    WGC_METHOD(StartCapture);
};
WGC_INTERFACE(Session2, IInspectable, 0x2c39ae40,0x7d2e,0x5044,{0x80,0x4e,0x8b,0x67,0x99,0xd4,0xcf,0x9e})
    WGC_METHOD(get_IsCursorCaptureEnabled, BYTE *);
    WGC_METHOD(put_IsCursorCaptureEnabled, BYTE);
};
WGC_INTERFACE(SessionStatics, IInspectable, 0x2224a540,0x5974,0x49aa,{0xb2,0x32,0x08,0x82,0x53,0x6f,0x4c,0xb5})
    WGC_METHOD(IsSupported, BYTE *);
};

#undef WGC_INTERFACE
#undef WGC_METHOD

inline constexpr wchar_t item_class[] = L"Windows.Graphics.Capture.GraphicsCaptureItem";
inline constexpr wchar_t pool_class[] = L"Windows.Graphics.Capture.Direct3D11CaptureFramePool";
inline constexpr wchar_t session_class[] = L"Windows.Graphics.Capture.GraphicsCaptureSession";
inline constexpr wchar_t fixture_class[] = L"FelixWgcFixtureWindow";
inline constexpr wchar_t fixture_env[] = L"FELIX_WGC_FIXTURE_TITLE";
inline constexpr wchar_t proxy_property[] = L"FelixWgcPortalProxy";

using CreateDeviceBridge = HRESULT (WINAPI *)(IDXGIDevice *, IInspectable **);
using CreateSurfaceBridge = HRESULT (WINAPI *)(IDXGISurface *, IInspectable **);
}
