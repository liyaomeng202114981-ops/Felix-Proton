# 在本机生成 Felix Proton UU Test 0.1.0-test.1

此脚本将历史运行器 `we-proton-ge11-11-31-desktop-netfix2` 的二进制文件和这次试用版的配套文件装入一个独立归档。需要 Linux、Python 3.10+、`zstd` 以及可写的输出目录。本次使用 Zstandard 1.5.7。复现历史二进制需要原来的 GE/WE-Proton 基底和模块构建过程。单独取得上游原版 runner 后执行本脚本，基底指纹检查会失败。

准备以下三个目录。

- `--base` 指向已验证的历史 netfix2 运行器，目录内可见 `proton`、`version` 和 `files/`。
- `--extras` 指向要装到包内 `felix/` 的完整已审核内容，包括试用入口、诊断器、对应源代码和许可、说明及验证材料。传入此目录本身。每次归档使用传入时的内容。
- `--metadata` 指向附带的 `metadata/` 或任何包含四份同版本标识文件的目录。需要 `compatibilitytool.vdf`、`version`、`we-proton-build-info` 和 `felix-build.json`。这些文件共同标识试用版和历史基底。

```sh
python3 package-local.py \
  --base /absolute/path/we-proton-ge11-11-31-desktop-netfix2 \
  --extras /absolute/path/reviewed/felix \
  --metadata /absolute/path/packaging/metadata \
  --output /absolute/path/dist/felix-proton-uu-test-0.1.0-test.1.tar.zst
zstd -t /absolute/path/dist/felix-proton-uu-test-0.1.0-test.1.tar.zst
tar --zstd -tf /absolute/path/dist/felix-proton-uu-test-0.1.0-test.1.tar.zst | head -20
sha256sum /absolute/path/dist/felix-proton-uu-test-0.1.0-test.1.tar.zst
```

`--output` 必须指向输入目录以外的新文件，父目录须已存在。解压后唯一顶层目录为 `felix-proton-uu-test-0.1.0-test.1/`。归档保留普通文件的执行位和指向树内的相对符号链接，归档所有者为数字 0，时间采用版本文件中的时间戳。压缩完成并核对历史内容后，脚本才原子创建最终文件。

基底指纹覆盖 9020 个入口的相对路径、种类、权限、文件大小或链接目标，并对普通文件逐个计算 SHA-256。指纹在已核对的暂存运行器与本机历史基底之间相同。排除项是三份待替换的旧标识文件、四个含本机构建信息的顶层项（两份 `README-*-BUILD.txt` 和两个 `*-build-provenance/`）、Python 缓存，以及历史误放的 `files/lib/wine/x86_64-windows/WeGameApps/`。基础发行的 `files/share/default_pfx/` 是随运行器交付的初始化模板。

配套目录由发布者逐项审核。脚本拒绝越界链接、设备文件、已知前缀/账号文件、会话目录和诊断输出（包括 JSONL、转储和捕获文件）。唯一允许的 `.log` 是已核对哈希的离线 SDK 冒烟输出。任意命名的普通文件仍需人工确认内容和来源。最终归档的 SHA-256 和解包检查是针对本次实际使用的配套内容和压缩器的发布证据。
