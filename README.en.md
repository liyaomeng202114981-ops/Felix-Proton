# Felix-Proton: UU / native Steam integration and connection protection

**Maintained by Felix Li, with OpenAI Codex assistance.** [中文](README.md)

Felix-Proton is an independently maintained Proton project based on WE-Proton source. It joins native Linux Steam and Windows UU to one network through their ordinary desktop icons. Standard Steam child processes usually inherit that network. The user selects the game, region, routing mode and node in UU.

**[Complete setup process — development notes (Chinese)](we/felix-proton/docs/FROM_ZERO.md)** · **[Implementation and code guide (Chinese)](we/felix-proton/docs/IMPLEMENTATION.md)** · **[Latest work report (Chinese)](we/felix-proton/docs/WORK_REPORT.md)** · [Current results and limits](we/felix-proton/docs/CURRENT_STATE.md) · [Ordinary-icon setup](we/felix-proton/src/native-ux/README.md) · [Source layout](we/felix-proton/README.md) · [Validation](we/felix-proton/docs/TESTING.md) · [Provenance](we/felix-proton/docs/PROVENANCE.md)

## Acknowledgments

Special thanks to **SHORiN-KiWATA** for developing and sharing WE-Proton and proton-wrapper. WE-Proton supplies the Wine Wintun and network interface support, while proton-wrapper manages the shared network session. Felix-Proton builds on their work and preserves upstream authorship, copyright notices, licenses and Git history. [WE-Proton](https://github.com/SHORiN-KiWATA/we-proton) · [proton-wrapper](https://github.com/SHORiN-KiWATA/proton-wrapper)

Thanks also to the contributors to Proton, Wine, GE-Proton, DW-Proton and passt / pasta for the compatibility, build and networking foundations. [Provenance and attribution](we/felix-proton/docs/PROVENANCE.md)

## Felix-Proton contributions

| Work | Implementation and result |
| --- | --- |
| Interface lifecycle fix 0062 | Filter stale Wine interface records after deletion or same-name recreation |
| Route-enumeration fix 0063 | Reuse successful translations within one enumeration, removing the regression introduced by 0062 and restoring performance near the historical baseline |
| Ordinary Steam / UU icons | Arrange shared networking, validate an existing Steam instance, preserve URI/arguments, and raise an existing window on repeated clicks |
| Steam CM protection | Keep discovered exact IPv4/TCP control endpoints on the pasta path; the local user confirmed the original Steam disconnect issue during acceleration switching was resolved |
| CM directory proxy | Query the Valve CM directory through a manually configured GNOME loopback proxy when available, and try a direct connection if the proxy connection fails |
| Steam protection notification | Show one notification per guard session when the rules are ready, including after recovery from a startup warning |
| Installation, rollback and diagnostics | Back up/restore desktop entries, query status, provide bounded passive diagnostics and accompanying tests |

The upstream wrapper supplies namespace/session management, WE-Proton supplies the Wintun foundation, and pasta supplies the host connection. The new Python guard installs precise endpoint rules only inside the shared private network. Host routes remain unchanged. It does not claim to protect every game connection.

## Validation and publication scope

This update covers development source, the complete configuration process, implementation details and known issues. Release builds, runner distribution and GitHub Releases are deferred.

All **66 isolated integration tests passed**, including directory proxy fallback and readiness notification checks. The earlier 64 integration tests, 16 collector tests and 45 portable-launcher tests remain historical results. The user separately confirmed that the latest CM update passed on their machine.

The project is maintained on `main` in this standalone repository. The launch integration and its documentation are under [`we/felix-proton/`](we/felix-proton/). A fresh installation requires a separately prepared, checksum-pinned historical test.1 runner.

Acceleration startup can take 10–30 seconds, which the user accepted; free resizing of UU is deferred. Cross-machine acceptance remains pending. IPv6, undiscovered endpoints, game connections and external network faults are outside the CM guard's guarantee. Historical Fossilize CPU activity was diagnosed and its settings retained at the user's request.

[Earlier network work and validation](we/network-integration) · [Upstream PR #1](https://github.com/SHORiN-KiWATA/we-proton/pull/1), checked open and unmerged on 2026-11-05. The Python additions are separate from that PR.

---

The upstream introduction follows unchanged. Its demonstrations, compatibility table, releases and installation commands belong to upstream; use the links above for Felix-Proton's additions.

# WE-Proton

[中文](README.md) | English

## About

On Linux (Wine / Proton), the WeGame client fails to download games, places windows in the wrong spot, misbehaves on input and shows black screens. This project is based on GE-Proton and DW-Proton: it starts from GE-Proton, adds DW-Proton's patches (compatibility fixes for anime games and others), and fixes the Wine / Proton / vkd3d-proton bugs behind those problems. The goal is to make the WeGame client itself, and games without kernel-level anti-cheat (single-player games, for example), run properly.

Companion launcher: [wegame-launcher](https://github.com/SHORiN-KiWATA/wegame-launcher) installs and runs WeGame in one step.

## About AI

The patches added by this project were written and debugged with the help of AI. The symptoms, root cause and verification of each patch are documented in [`we/fixes/`](we/fixes/) (in Chinese).

## Competitive games and anti-cheat

- This project does not fix or support competitive games such as Delta Force or VALORANT. Issues about them will be closed.
- This project does not adapt to ACE or any other anti-cheat, and does not accept requests or code that bypass anti-cheat or relate to cheating.
- Linux is not a platform supported by ACE. Even if a game with ACE runs, the account may still be banned for an abnormal environment. You bear the consequences, including bans, of using this project.

## Demo

https://github.com/user-attachments/assets/42438b93-5a36-4557-8a0f-4b65b53d5e07

## Installation

1. Download `we-proton-<version>.tar.xz` from [Releases](https://github.com/SHORiN-KiWATA/we-proton/releases)
2. Extract it into your launcher's Proton directory:
   - wegame-launcher: `~/.local/share/proton/runners/`
   - Steam: `~/.local/share/Steam/compatibilitytools.d/`
   - Lutris, Heroic and others: their own Proton / runner directory
3. Select `we-proton-<version>` in the launcher. wegame-launcher uses the newest WE-Proton it finds by default; to pick one by hand, use Settings → Runner in the GUI, or run

   ```
   wegame-launcher runner we-proton-<version>
   ```

Notes:

- The prefix version is the same as that of the GE-Proton release it is based on (`GE-Proton11-11`). Coming from an older WE-Proton based on DW-Proton (`we-proton-11.0-14-*`), the prefix is upgraded once. The log then says `Prefix has an invalid version?!`: GE-Proton's script doesn't understand versions starting with `dwproton-`, skips its own upgrade steps and leaves the update to Wine, which is fine
- 0005 needs userfaultfd asynchronous write-protection, available in Linux 6.7 and later; on older kernels that fix is inactive and everything else works as usual

## Building from source

Needs docker. The first full build takes a few hours:

```
git clone https://github.com/SHORiN-KiWATA/we-proton.git
cd we-proton
we/build.sh --name we-proton-<version>             # output in build/
we/build.sh --name we-proton-<version> --install   # also install to "~/.local/share/proton/runners/WE-Proton Latest"
```

The script fetches the submodules, patches them with `patches/protonprep-valve-staging.sh` (GE-Proton's patches, then DW-Proton's and WE-Proton's) and runs `make redist` in the Steam Linux Runtime SDK container. The details, the test programs, the diagnostic tools and how to follow new upstream releases are described in [`we/README.md`](we/README.md) (in Chinese).

## Repository layout

- `patches/wine/`, `patches/vkd3d-proton/we-*.patch`: WE-Proton's patches
- `patches/dwproton/`: Wine patches DW-Proton has and GE-Proton doesn't
- The rest of `patches/` and `patches/protonprep-valve-staging.sh`: GE-Proton's patches and patching script (`protonfixes/0003`–`0006` come from DW-Proton; `protonfixes/0051` is WE-Proton's own). The submodules stay at the upstream commits; the script applies all patches before the build
- `we/fixes/`: one report per patch (symptoms, root cause, fix, verification)
- `we/tests/`: test programs and their output before and after each fix
- `we/diag/`: diagnostic patches and scripts, not part of the release build
- `we/build.sh`: the build script
- `we/sync/`, `we/upstream-sync.md`: scripts and a step-by-step guide for following new GE-Proton and DW-Proton releases
- Everything else is GE-Proton's / Proton's own content

## Source and licenses

- Proton's top-level contents: BSD-3-Clause (Valve Corporation, see [`LICENSE`](LICENSE) and [`LICENSE.proton`](LICENSE.proton))
- Wine: Valve's Wine plus the patches in `patches/`, LGPL-2.1
- vkd3d-proton: upstream vkd3d-proton plus the patches in `patches/vkd3d-proton/`, LGPL-2.1; the dxil-spirv subproject and the patch to it are MIT
- Other components: see the `LICENSE` / `COPYING` files in their directories, and `LICENSE`, `LICENSE.OFL` and `PATENTS.AV1` in the release package
- The scripts and documents under `we/` are under BSD-3-Clause as well

## Acknowledgements

- [Proton](https://github.com/ValveSoftware/Proton) by Valve and CodeWeavers
- [GE-Proton](https://github.com/GloriousEggroll/proton-ge-custom) by GloriousEggroll
- [DW-Proton](https://dawn.wine/dawn-winery/dwproton) by Dawn Winery
- [Wine](https://www.winehq.org/), [DXVK](https://github.com/doitsujin/dxvk), [vkd3d-proton](https://github.com/HansKristian-Work/vkd3d-proton) and the other projects Proton is built from
