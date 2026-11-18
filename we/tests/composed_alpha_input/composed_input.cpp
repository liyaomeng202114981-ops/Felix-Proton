/* SPDX-License-Identifier: BSD-3-Clause
 * Copyright 2026 Felix Li, with OpenAI Codex assistance. */
#define UNICODE
#define _UNICODE
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d11.h>
#include <stdio.h>

static ID3D11Device *device;
static ID3D11DeviceContext *context;
static IDXGISwapChain *swapchain;
static ID3D11RenderTargetView *target;
static unsigned int frames;

static LRESULT CALLBACK window_proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp)
{
    if (msg == WM_PAINT)
    {
        PAINTSTRUCT ps;
        HDC dc = BeginPaint(hwnd, &ps);
        RECT rect;
        GetClientRect(hwnd, &rect);
        HBRUSH brush = CreateSolidBrush(RGB(34, 85, 119));
        FillRect(dc, &rect, brush);
        DeleteObject(brush);
        SetBkMode(dc, TRANSPARENT);
        TextOutW(dc, 20, 12, L"Opaque parent with independently presented child", 47);
        EndPaint(hwnd, &ps);
        return 0;
    }
    if (msg == WM_TIMER && target)
    {
        const float color[] = {0.2f, (frames++ % 60) / 60.0f, 0.7f, 1.0f};
        context->ClearRenderTargetView(target, color);
        swapchain->Present(0, 0);
        return 0;
    }
    if (msg == WM_DESTROY) { PostQuitMessage(0); return 0; }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR command, int show)
{
    WNDCLASSW wc = {};
    wc.lpfnWndProc = window_proc;
    wc.hInstance = instance;
    wc.lpszClassName = L"FelixComposedInputParent";
    RegisterClassW(&wc);
    HWND parent = CreateWindowW(wc.lpszClassName, L"Felix composed input parent",
        WS_OVERLAPPEDWINDOW | WS_CLIPCHILDREN | WS_VISIBLE, 40, 40, 700, 480,
        NULL, NULL, instance, NULL);
    HWND child = CreateWindowW(L"STATIC", L"Felix GPU child", WS_CHILD | WS_VISIBLE,
        120, 150, 320, 180, parent, NULL, instance, NULL);
    DXGI_SWAP_CHAIN_DESC desc = {};
    desc.BufferDesc.Width = 320;
    desc.BufferDesc.Height = 180;
    desc.BufferDesc.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
    desc.SampleDesc.Count = 1;
    desc.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
    desc.BufferCount = 1;
    desc.OutputWindow = child;
    desc.Windowed = TRUE;
    desc.SwapEffect = DXGI_SWAP_EFFECT_DISCARD;
    HRESULT hr = D3D11CreateDeviceAndSwapChain(NULL, D3D_DRIVER_TYPE_HARDWARE, NULL,
        D3D11_CREATE_DEVICE_BGRA_SUPPORT, NULL, 0, D3D11_SDK_VERSION, &desc,
        &swapchain, &device, NULL, &context);
    ID3D11Texture2D *buffer = NULL;
    if (SUCCEEDED(hr)) hr = swapchain->GetBuffer(0, __uuidof(ID3D11Texture2D), (void **)&buffer);
    if (SUCCEEDED(hr)) hr = device->CreateRenderTargetView(buffer, NULL, &target);
    if (buffer) buffer->Release();
    FILE *file = fopen("Z:\\opt\\felix-case\\composed-ready.json", "wb");
    if (file)
    {
        fprintf(file, "{\"hr\":%ld,\"parent\":%llu,\"child\":%llu}\n", (long)hr,
            (unsigned long long)(ULONG_PTR)parent, (unsigned long long)(ULONG_PTR)child);
        fclose(file);
    }
    if (FAILED(hr)) return 4;
    SetTimer(parent, 1, 33, NULL);
    MSG msg;
    while (GetMessageW(&msg, NULL, 0, 0) > 0) { TranslateMessage(&msg); DispatchMessageW(&msg); }
    target->Release(); swapchain->Release(); context->Release(); device->Release();
    return 0;
}
