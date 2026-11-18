# Native maximized caption-move fixture

BSD-3-Clause; Copyright 2026 Felix Li, with OpenAI Codex assistance.

Owned Win32 fixture and private GNOME driver used for patch 0069. No vendor
client, account or downloaded binary is included. This extends the existing
edge fixture with maximize/restore file controls and a maximize box; the
`corrected` mode relays real child-window caption hits to the main window.

Build in the fixed Steam Runtime SDK:

```sh
x86_64-w64-mingw32-gcc-posix -O2 -static edge_fixture.c -o edge_fixture.exe -luser32 -lshell32
```

Requires GNOME Shell 50, Python GI, a matching runtime/runner and a disposable
test account environment. Run each command with absolute paths:

```sh
WINE_X11_NATIVE_MAXIMIZED_MOVE=0 bash run.sh x11 /absolute/runner/proton /absolute/SteamLinuxRuntime_4/_v2-entry-point /absolute/edge_fixture.exe 1
WINE_X11_NATIVE_MAXIMIZED_MOVE=1 bash run.sh x11 /absolute/runner/proton /absolute/SteamLinuxRuntime_4/_v2-entry-point /absolute/edge_fixture.exe 1
```

The script creates a fresh HOME/config/dconf/prefix, private D-Bus and headless
1280×800 compositor. Before sending input, the Python driver verifies the
RemoteDesktop bus owner's PID/UID, `--headless`, private display name and exact
HOME/runtime paths. Only that compositor's pointer is used. No real account,
host input device or game is a test target. The outer timeout bounds the case;
the fixture also has a 60s watchdog. Preserve outputs and verify no processes
with that exact private HOME/prefix remain before considering cleanup complete.

`native.wine11.0-{off,on}.txt` and `custom-frame.wine11.0-{off,on}.tsv` are actual
results. With the flag off, the custom-frame window moves normally and receives
`SC_MOVE|HTCAPTION` when maximized, but remains maximized. With the flag on it
restores from 1280×768 to 640×420 and continues moving. In both cases tiling
produces 640×768 and dragging out restores 640×420. A maximized bottom-right
resize reaches `SC_SIZE` and stays maximized, unchanged by the flag.

The ordinary decorated control restores from maximization in both modes. Its
normal-state sample did not exercise a usable caption point and is **not** a
positive normal-drag control. The custom-frame normal drag is the positive
control. An initial early-state run was retained privately and superseded by
settled-state runs; its normal result is not used as passing evidence.

`native-maximized-move-validation.json` records assertions and private-process
cleanup. `user32-comparison.json` is a separate actual Wine conformance run:
the combined candidate with alpha=1 and native move=1 has the same 38 existing
failure messages as the input-only candidate (149 todo, 2 skips), not a full
pass. No Windows, keyboard-move runtime, other compositor, native Wine Wayland,
real client acceptance or long-duration performance result is implied.
