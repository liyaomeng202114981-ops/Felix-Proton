# Profiled layered-decoration fullscreen fixture

BSD-3-Clause; Copyright 2026 Felix Li, with OpenAI Codex assistance.

The source is [`../layered-helper-fullscreen.c`](../layered-helper-fullscreen.c).
It creates 13 synthetic owner/helper pairs, with no third-party application,
account, hooks or host input. This exercises patch 0070 on GNOME Shell/Mutter
50.1 with XWayland. Windows was not tested; no Windows result is implied.

Build a static PE in the fixed Steam Runtime SDK:

```sh
x86_64-w64-mingw32-gcc-posix -O2 -Wall -Wextra -Werror -static -municode layered-helper-fullscreen.c -o layered-helper-fullscreen.exe -luser32
```

Use absolute paths to a candidate runner, Steam Linux Runtime 4 entry point
and the compiled fixture. The driver creates a private HOME, dconf, prefix,
D-Bus and headless compositor. It verifies the compositor PID, UID, private
runtime and display before observing X11 windows. It sends no input.

```sh
WINE_LAYERED_OVERLAY_ALPHA=1 WINE_X11_NATIVE_MAXIMIZED_MOVE=1 WINE_X11_NO_FULLSCREEN_LAYERED_HELPER=1 WINE_X11_NO_FULLSCREEN_HELPER_CLASS=SyntheticLayeredFullscreen bash /absolute/tests/layered_helper_fullscreen/run.sh x11 /absolute/candidate/proton /absolute/SteamLinuxRuntime_4/_v2-entry-point /absolute/layered-helper-fullscreen.exe 1
```

Repeat with the pre-0070 runner and the same flags, then with the candidate
and an unset flag, `0`, `2`, missing class and `UnmatchedSyntheticClass`.
Each case prints `RESULT_DIRECTORY`, containing `observed.json` and
`fixture-cleanup.json`. These directories include generated runtime copies;
keep evidence and confirm no processes or mounts use a case before cleaning
only its generated runtime copy. On this host, repeated copies exhausted the
temporary filesystem quota before one fixture could start; that case was
rerun after scoped cleanup and was not counted as a code failure or a pass.

Actual sanitized results are `layered-helper.wine11.0-{before,after}.json`
and `matrix.wine11.0.json`. Six explicitly declared decoration roles lose
inferred fullscreen and receive zero GTK frame extents; seven guards and
all owner properties retain their baseline behavior. Unset/0/2/missing or
wrong class match the pre-0070 runner. The benchmark additionally assigns
`[2,3,4,5]` to an initially unowned helper before making it owned and
changing its geometry. All configurations preserve the supplied property.
The fixture exits normally and leaves no mapped fixture windows.

`user32-comparison.json` records actual Wine `user32 win` results: 77,978
assertions, 149 todo, two skips and the same 38 failure/unexpected-todo-success
messages before and after. This is a regression comparison, not a full pass.
No other compositor, Wine Wayland, i386 Unix, mixed DPI, multiple displays,
long-duration behavior or complete release build is verified here.
