#!/bin/bash
set -euo pipefail

here=$(cd -- "$(dirname -- "$0")" && pwd)
observer=felix-ui-benchmark@local

if [[ ${1:-} == --private-session ]]; then
    shift
    case_dir=$1
    backend=$2
    test "$XDG_RUNTIME_DIR" = "$case_dir/runtime"
    test -n "$DBUS_SESSION_BUS_ADDRESS"

    gsettings set org.gnome.shell enabled-extensions "['$observer']"
    gsettings set org.gnome.shell disable-user-extensions false
    gsettings set org.gnome.desktop.wm.preferences mouse-button-modifier '<Super>'
    gsettings set org.gnome.desktop.wm.preferences resize-with-right-button false

    export WAYLAND_DISPLAY=felix-ui-benchmark
    options=(--headless --virtual-monitor=1280x800 --wayland-display="$WAYLAND_DISPLAY")
    if [[ "$backend" == native ]]; then
        options+=(--no-x11)
        export PROTON_ENABLE_WAYLAND=1 WINE_GRAPHICS_DRIVER=wayland
        if [[ ${FELIX_UI_BENCH_PROTOCOL:-0} == 1 ]]; then
            export WAYLAND_DEBUG=client WINEDEBUG=-all,+waylanddrv,+cursor,+msg
        fi
    else
        export PROTON_ENABLE_WAYLAND=0 WINE_GRAPHICS_DRIVER=x11
    fi

    gnome-shell "${options[@]}" >"$case_dir/gnome.log" 2>&1 &
    shell_pid=$!
    trap 'kill "$shell_pid" 2>/dev/null || true; wait "$shell_pid" 2>/dev/null || true' EXIT
    for ((i=0;i<100;i++)); do
        if [[ "$backend" == x11 ]]; then
            display=$(sed -nE 's/.*Using public X11 display (:([2-9]|[1-9][0-9]+)),.*/\1/p' "$case_dir/gnome.log" | head -1)
            auth=$(find "$XDG_RUNTIME_DIR" -maxdepth 1 -name '.mutter-Xwaylandauth.*' -print -quit)
            if [[ -n "$display" && -f "$auth" ]]; then
                export DISPLAY="$display" XAUTHORITY="$auth"
            fi
        fi
        if [[ -s "$FELIX_UI_BENCH_SNAPSHOT" && ( "$backend" == native || -n "${DISPLAY:-}" ) ]]; then
            break
        fi
        sleep .15
    done
    test -s "$FELIX_UI_BENCH_SNAPSHOT"
    if [[ "$backend" == x11 ]]; then xprop -root _NET_SUPPORTING_WM_CHECK >/dev/null; fi
    /usr/bin/python3 "$here/benchmark.py" "$@"
    exit
fi

if (( $# < 4 || $# > 5 )) || [[ "$1" != x11 && "$1" != native ]]; then
    printf 'Usage: %s x11|native PROTON RUNTIME_ENTRY FIXTURE_EXE [ROUNDS]\n' "$0" >&2
    exit 2
fi
backend=$1
caption_patch=${FELIX_UI_BENCH_CAPTION_PATCH:-0}
if [[ "$caption_patch" != 0 && ( "$caption_patch" != 1 || "$backend" != x11 ) ]]; then
    printf 'The caption-edge patch profile requires FELIX_UI_BENCH_CAPTION_PATCH=1 and the x11 backend.\n' >&2
    exit 2
fi
runner=$(realpath -e -- "$2")
runtime=$(realpath -e -- "$3")
fixture=$(realpath -e -- "$4")
rounds=${5:-3}
if [[ ! "$rounds" =~ ^([1-9]|1[0-9]|20)$ || ! -x "$runner" || ! -x "$runtime" || ! -f "$fixture" ]]; then
    printf 'Expected executable Proton and runtime entry points, a fixture PE, and 1–20 rounds.\n' >&2
    exit 2
fi

case_dir=$(mktemp -d "/tmp/felix-ui-benchmark-$backend.XXXXXXXX")
mkdir -m 700 "$case_dir"/{runtime,home,config,cache,data,state,pv-var,steam-stub,compatdata}
extension="$case_dir/data/gnome-shell/extensions/$observer"
mkdir -p "$extension"
cp "$here/extension.js" "$extension/"
printf '%s\n' '{"name":"Felix UI benchmark observer","description":"Reports only synthetic fixture geometry","uuid":"felix-ui-benchmark@local","shell-version":["50"]}' >"$extension/metadata.json"
printf '%s\n' 'user-db:user' >"$case_dir/dconf-profile"
install -m 700 "$fixture" "$case_dir/edge_fixture.exe"
printf 'case=%s\n' "$case_dir"
limit=$((90 + (50 + 20 * caption_patch) * rounds))
exec timeout "${limit}s" env -u DISPLAY -u WAYLAND_DISPLAY -u XAUTHORITY -u DBUS_SESSION_BUS_ADDRESS \
    -u SESSION_MANAGER -u GNOME_SHELL_SESSION_MODE -u WAYLAND_DEBUG -u WINEPREFIX -u WINEARCH -u PROTON_USE_WAYLAND \
    -u WINE_X11_CAPTION_EDGE_RESIZE \
    HOME="$case_dir/home" XDG_RUNTIME_DIR="$case_dir/runtime" XDG_CONFIG_HOME="$case_dir/config" XDG_CACHE_HOME="$case_dir/cache" \
    XDG_DATA_HOME="$case_dir/data" XDG_STATE_HOME="$case_dir/state" DCONF_PROFILE="$case_dir/dconf-profile" GIO_USE_VFS=local \
    FELIX_UI_BENCH_SNAPSHOT="$case_dir/snapshot.json" PRESSURE_VESSEL_VARIABLE_DIR="$case_dir/pv-var" \
    PRESSURE_VESSEL_FILESYSTEMS_RW="$case_dir" PRESSURE_VESSEL_FILESYSTEMS_RO="${runner%/*}" \
    STEAM_COMPAT_DATA_PATH="$case_dir/compatdata" STEAM_COMPAT_CLIENT_INSTALL_PATH="$case_dir/steam-stub" \
    SteamAppId=0 SteamGameId=0 PROTON_DESKTOP_IMPORT=0 PROTONFIXES_DISABLE=1 PROTON_USE_XALIA=0 PROTON_NO_FSYNC=1 PROTON_USE_WOW64=1 \
    WINEDLLOVERRIDES="mscoree,mshtml,winemenubuilder.exe=d" WINEDEBUG=-all PROTON_LOG=0 \
    dbus-run-session -- bash "$here/run.sh" --private-session "$case_dir" "$backend" "$runner" "$runtime" "$rounds" \
    "$case_dir/edge_fixture.exe" 2>"$case_dir/session.log"
