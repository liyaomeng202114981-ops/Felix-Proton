# Felix-Proton test.1: component notices and corresponding source

Maintained by **Felix Li, with OpenAI Codex assistance**, based on **SHORiN-KiWATA's WE-Proton and proton-wrapper**, and the contributors to Proton, Wine, GE-Proton, DW-Proton and passt/pasta. Original authors, copyright notices and licenses remain in place. These notices do not replace any component license.

The fixed `felix-proton-uu-test-0.1.0-test.1.tar.zst` is an unchanged historical binary repack, **not** a new complete Wine/Proton build. Its manifest identifies the downstream desktop 0061 and network 0062/0063 module builds. Retain its LICENSE, COPYING.7zip, LICENSE.7zip, LICENSE.OFL and PATENTS.AV1, and all licenses in the supplied source trees.

## Source sets shipped beside the runner

- `felix-proton-uu-test.1-modified-wine-source.tar.zst` contains the complete already-patched Wine tree, exact historical desktop Python integration, the 0061/0062/0063 patches, SDK-side compilation recipes, original-to-published source maps and module provenance. Its SDK, source hashes and two architectures are recorded. Do not apply the patches twice. Historical host scripts are provenance; the flat source snapshot has a separate isolated module-build recipe.
- `we-proton-4617d991-build-source.tar.zst` contains the matching base build project, Makefile/configure rules and complete patch collection at the recorded base revision. Root submodule content is supplied separately.
- `we-proton-ge11-11-31-source.tar.xz` is the unchanged original upstream release source. It includes the base patched Wine, DXVK, vkd3d-proton and 7-Zip, including the nested sources included by that release.
- `felix-proton-test.1-dependency-sources.tar.zst` contains hash-locked original upstream archives plus required nested sources and non-gitlink build inputs. `SOURCE_LOCK.json` records every source URL, revision, length, digest and dependency relationship. Archive-internal license/copyright texts are preserved without flattening or relicensing them.
- Current installer, launch integration, Steam CM protection, pairing-tool source and tests accompany the installation bundle and are maintained at https://github.com/liyaomeng202114981-ops/Felix-Proton . The executable Python additions inside the historical runner remain inspectable in that runner as well.

## License boundaries

Wine and the downstream Wine changes retain **LGPL-2.1-or-later**. vkd3d-proton, libmspack, procps-ng and other libraries retain their provided LGPL/GPL terms and per-file notices. Espeak-ng's source and data retain its GPL terms. Wine-Gecko retains the original Mozilla/Wine component licenses. Wine-Mono retains its mixed original licenses, with its official source release and included nested code. The Wine-Mono patch stack is in the base build source.

7-Zip includes LGPL terms, the unRAR restriction and per-file BSD/public-domain terms. Fonts retain their font licenses. ICU retains its Unicode/ICU license and upstream notices; the base project's `icu/README.md` identifies version 68.2 despite the historical filename spelling `6.8.2`. ONNX Runtime, Piper, Piper-Phonemize, fmt, spdlog, the Vulkan components, Xalia, zenity-rs and their dependencies retain each source tree's own license and third-party notices. No blanket BSD license is applied to this runtime or its dependency bundle.

The current Felix Python integration and source-packaging code are BSD-3-Clause where declared. The wrapper and pasta are distinct projects with their own notices; their source/binary materials are described separately by the setup bundle. Steam, UU, their icons, client installers, accounts, game content and user prefixes are not redistributed here.

## Build and verification scope

Source availability and matching module manifests establish provenance, not a promise of a bit-for-bit full-runner rebuild or universal compatibility. Historical PE32 tests used WoW64; a compiled i386 Unix module does not establish legacy-i386 runtime acceptance. The optional ARM FEX toolchain is not shipped by this x86-64 runner, so its large test-binary submodules are outside this runtime source bundle. Upstream build recipes may require their separately specified SDK and build tools.

The distribution preserves original source and license files. The source-materials tool reads and hashes archives; it never executes component source, runs a game or installs into an active prefix.
