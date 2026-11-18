# Composed alpha input-region fixture

BSD-3-Clause; Copyright 2026 Felix Li, with OpenAI Codex assistance.

Exact owned GDI-parent/D3D11-child source and isolated sample/output used for
Wine patch 0068. No account, proprietary application, runtime or PE binary is
included. Native Windows was not tested; no Windows result is supplied.

The parent paints an opaque 692×446 client area. A 320×180 child independently
presents D3D11 frames at (120,150). With the existing alpha opt-in, the baseline
replaces the whole parent's input region with just the child's pixels: three
opaque parent points no longer accept input. The candidate preserves all four
points while keeping the parent's recorded RGBA controls unchanged.

Build statically with the Steam Runtime SDK mingw compiler:

```sh
x86_64-w64-mingw32-g++-posix -O2 -static -municode composed_input.cpp -o composed_input.exe -luser32 -ld3d11 -ldxgi -lgdi32
```

Use two disposable offline Xvfb sessions with private D-Bus, fresh prefixes,
software Vulkan and wrapper/SLR4: original v2 driver, then separate candidate.
Set `PROTON_USE_WINED3D=0` and `WINE_LAYERED_OVERLAY_ALPHA=1` for both. Do not
connect this fixed-layout sample script to a user desktop or account prefix.
Map output at `/opt/felix-case` with a `screens` directory, launch the fixture,
then run `sample_composed.py` **inside the private X server**. It reads only
owned fixture metadata, pixels and input shape. The fixture has no internal
shutdown timer: bound the disposable session (tested maximum 180s), then stop
it and verify all namespace descendants are gone.

`composed.wine11.0-baseline.txt` and `composed.wine11.0-candidate.txt` are actual
before/after output. `composed-comparison.json` records the assertions and
cleanup. The test has no window manager and does not prove native maximize,
edge tiling, dragging, or Wine Wayland behavior.

Additional recorded controls: three official Electron 36.4.0 pixel controls
and GDI/ULW full-RGBA hashes remain unchanged; Wine user32 win has the same
38 existing failure messages before/after (not a full pass).
`empty-helper-validation.json` records two fully transparent, mapped helpers
with empty input regions and the rejected fixture attempts. The first added
blank sample had scrollbars; a separate transparent test enabled ignore-mouse
**after showing** to match the tested sequence. Pre-show variants were unmapped
and are not passing evidence. Exact auxiliary fixture sources, samplers and before/after output are under
`auxiliary/`. They use the official Electron 36.4.0 archive and the same private
layout documented in [the ARGB fixture](../argb_client_fixture/README.md); keep
its licenses. The GDI/ULW source is also in that existing fixture. No Windows
output or host-GPU test is implied.
