# Runtime source materials

The x86-64 test.1 runner is distributed with its matching historical modified-Wine source, original upstream patched source, base build project, and a hash-locked dependency source bundle. `SOURCE_INDEX.json` at the release root connects those files to the runner. All original component licenses are retained.

To recreate this dependency archive, obtain this directory from the matching Felix-Proton source revision and run:

```sh
python3 -B build_sources.py --cache /absolute/source-cache --output-dir /absolute/new-output --fetch
```

The Python standard library and `zstd` are required. `--fetch` downloads only missing original source archives from the frozen HTTPS URLs, checks every byte length and SHA-256, and stops on mismatch. Omit it to build using an existing complete cache without network access. The command creates `felix-proton-test.1-dependency-sources.tar.zst`, `SOURCE_INDEX.json`, and `THIRD_PARTY_NOTICES.md`; it refuses to overwrite release files. It does not compile or install any component.

The archive contains each original source archive under `archives/`, a clean source lock, these notices, and a per-archive `SHA256SUMS`. Extract original component archives separately, retaining their license files. Place nested gitlink sources at the parent-relative path recorded in `component`/`required_by` when rebuilding that parent. Original DXVK/vkd3d nested sources are also present in the separately supplied upstream patched-source archive.

Use the base project's Makefile/patches and the modified-Wine snapshot's build recipes for their respective build stages. These files document historical inputs and provide the matching source; they do not claim a newly executed full build or bit-identical full-runner reproducibility. Runtime installation does not require downloading source archives.
