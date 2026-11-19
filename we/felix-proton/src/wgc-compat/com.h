// SPDX-License-Identifier: BSD-3-Clause
// Copyright 2026 Felix Li, with OpenAI Codex assistance.
#pragma once
#include "abi.h"
#include <atomic>
#include <mutex>
#include <new>
#include <utility>
#include <vector>
#include <wrl/client.h>

namespace wgc {
using Microsoft::WRL::ComPtr;

template<class Interface> const GUID &iid_of() { return Interface::iid; }
template<> inline const GUID &iid_of<IActivationFactory>() { return __uuidof(IActivationFactory); }
template<> inline const GUID &iid_of<IAgileObject>() { return IID_IAgileObject; }

template<class Derived, class First, class... More>
class Object : public First, public More..., public IAgileObject {
    std::atomic<ULONG> refs_{1};

    template<class Interface> bool match(REFIID iid, void **out) {
        if (iid != iid_of<Interface>())
            return false;
        *out = static_cast<Interface *>(this);
        return true;
    }

public:
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void **out) final {
        if (!out) return E_POINTER;
        *out = nullptr;
        if (iid == IID_IUnknown || iid == __uuidof(IInspectable))
            *out = static_cast<First *>(this);
        else if (!(match<First>(iid, out) || (match<More>(iid, out) || ...) ||
                   match<IAgileObject>(iid, out)))
            return E_NOINTERFACE;
        AddRef();
        return S_OK;
    }
    ULONG STDMETHODCALLTYPE AddRef() final { return ++refs_; }
    ULONG STDMETHODCALLTYPE Release() final {
        const ULONG count = --refs_;
        if (!count) delete static_cast<Derived *>(this);
        return count;
    }
    HRESULT STDMETHODCALLTYPE GetIids(ULONG *count, IID **ids) final {
        if (!count || !ids) return E_POINTER;
        const IID supported[] = {iid_of<First>(), iid_of<More>()...};
        *count = 0;
        *ids = static_cast<IID *>(CoTaskMemAlloc(sizeof(supported)));
        if (!*ids) return E_OUTOFMEMORY;
        memcpy(*ids, supported, sizeof(supported));
        *count = ARRAYSIZE(supported);
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE GetRuntimeClassName(HSTRING *name) final {
        return WindowsCreateString(Derived::name, lstrlenW(Derived::name), name);
    }
    HRESULT STDMETHODCALLTYPE GetTrustLevel(TrustLevel *level) final {
        if (!level) return E_POINTER;
        *level = BaseTrust;
        return S_OK;
    }
};

template<class Sender>
class Events {
    struct Entry { EventRegistrationToken token; ComPtr<Handler<Sender>> callback; };
    std::mutex mutex_;
    std::vector<Entry> entries_;
    INT64 next_ = 0;
public:
    HRESULT add(Handler<Sender> *callback, EventRegistrationToken *token) {
        if (!callback || !token) return E_POINTER;
        try {
            std::lock_guard lock(mutex_);
            const EventRegistrationToken id{++next_};
            entries_.push_back({id, ComPtr<Handler<Sender>>(callback)});
            *token = id;
            return S_OK;
        } catch (const std::bad_alloc &) {
            return E_OUTOFMEMORY;
        }
    }
    HRESULT remove(EventRegistrationToken token) {
        ComPtr<Handler<Sender>> released;
        std::lock_guard lock(mutex_);
        for (auto it = entries_.begin(); it != entries_.end(); ++it) {
            if (it->token.value == token.value) {
                released = std::move(it->callback);
                entries_.erase(it);
                break;
            }
        }
        return S_OK;
    }
    void clear() {
        std::vector<Entry> old;
        std::lock_guard lock(mutex_);
        old.swap(entries_);
    }
    void invoke(Sender *sender) {
        std::vector<Entry> snapshot;
        try {
            std::lock_guard lock(mutex_);
            snapshot = entries_;
        } catch (const std::bad_alloc &) {
            return;
        }
        for (const auto &entry : snapshot)
            entry.callback->Invoke(sender, nullptr);
    }
};
}
