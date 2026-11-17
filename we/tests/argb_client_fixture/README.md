# ARGB out-of-process client fixture

BSD-3-Clause; Copyright 2026 Felix Li, with OpenAI Codex assistance.

These are exact copies of the synthetic sources used for the 0067 comparison,
plus their isolated output. No downloaded runtime or generated PE binary is
included. No test was run on native Windows; there is no Windows result file.

The GPU fixture creates an opaque control, a transparent owned window with
mouse pass-through after showing it, and a transparent popup. Each has a grey
card, changing frame text and a **real opaque black square**. The empty tail
must become transparent without removing the black square or changing the
opaque control. The test quits after 180 seconds.

Use the official Electron **36.4.0 win32-x64** archive. SHA256:
`06ac065519743b4e5fc16f61272542313385cc0de849d2589db1f2f8e5e6effb`.
[Release and checksums](https://github.com/electron/electron/releases/tag/v36.4.0).
Keep the runtime's own licenses. This fixture does not install dependencies.

## Isolated layout and compilation

The tested paths are deliberately retained. Set up a disposable offline Xvfb,
private D-Bus and clean prefix with no host audio/GPU/input/accounts, using
SLR4 and the normal wrapper. Map only these test materials into its private
mount namespace:

- `/opt/felix-materials/window_metadata.exe`: the compiled helper below.
- `/opt/felix-case`: writable test output; create its `screens` subdirectory.
- Extract Electron and put `main.js`, `fixture.html`, `package.json` under its
  `resources/app/` directory. The prefix C: is disposable.

Build the Win32 helpers with static mingw, from this directory:

```sh
x86_64-w64-mingw32-g++ -O2 -static -municode -mwindows alpha_fixture.cpp -o alpha_fixture.exe -lgdi32
x86_64-w64-mingw32-g++ -O2 -std=c++17 -static -municode window_metadata.cpp -o window_metadata.exe -lpsapi
```

Launch `electron.exe` through wrapper/SLR4 twice, with identical DXVK and
software-Vulkan configuration and `WINE_LAYERED_OVERLAY_ALPHA=1`: first an
unmodified rebuilt driver, then the candidate driver in a separate runner.
Wait until all three windows are visible and their fade-in has settled, then
run `python3 sample_electron.py` **inside that private X server only**.
It reads drawable RGBA and saves PNGs without modifying pixels. Reading a
24bit drawable's padding is not evidence of native alpha: require depth32.
`main.js --software-ui` provides a separate software-rendering control.

The metadata helper enumerates windows belonging to the executable passed
as argv[1], comparing file IDs across DOS aliases. It only reads documented
window/process metadata; it neither injects code nor changes windows. The
second argument selects a JSON output file. The fixture calls it at the
private paths above. `alpha_fixture.exe` independently checks GDI and ULW;
its result goes to `C:\alpha-fixture-result.json` and it exits after 45s.

Terminate the private session and verify namespace descendants are gone.
Never point this fixed-layout diagnostic at a desktop X server or a live
account prefix. It is a reproducer, not a general capture utility.

## Recorded output

- `electron.wine-baseline.txt`: rebuilt original with alpha opt-in; both
  transparent windows still have `[0,0,0,255]` tails.
- `electron.wine-alpha-v2.txt`: candidate, same configuration; both tails
  `[0,0,0,0]`, grey/true-black controls retain alpha255.
- `gdi-comparison.json`: byte-identical GDI/ULW hashes before and after.
- `user32-comparison.json`: actual Wine win conformance comparison. Both
  runs have 38 existing failures; one already-failing foreground assertion
  returns a different handle. No new failure site, **not a full pass**.

Private DXVK runs used software Vulkan; they do not establish hardware GPU
compatibility. The runtime build's independent test output is not a Windows
comparison. Details, failures and source provenance are in the 0067 report.
