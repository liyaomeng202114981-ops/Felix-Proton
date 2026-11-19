# Ubuntu 选窗与 WGC 兼容层

此目录记录 2026-11-19 已安装并验证的直播伴侣选窗实现。用户在 Ubuntu 系统选择器中授权窗口，兼容层按授权把 PipeWire DMA-BUF 转成伴侣「窗口」素材使用的 D3D11 纹理。每个授权有自己的帧通道。受测环境使用 GNOME Wayland、XWayland 和 x86-64 Proton。

## 源码入口

| 工作 | 入口 |
| --- | --- |
| 收起伴侣旧选择框、自动选入已授权窗口 | [inapp_actions.cpp](inapp_actions.cpp) |
| 按次授权、追踪素材、取消和删除清理 | [inapp.py](inapp.py) · [douyin_native.py](douyin_native.py) |
| 系统授权和可选的 GNOME 选中项标题 | [portal.py](../wayland-capture/portal.py) · [portal_title.py](portal_title.py) |
| 独立来源编号、WGC 帧池和 D3D11 导出 | [wgc.cpp](wgc.cpp) · [protocol.h](dmabuf/protocol.h) · [build.py](build.py) |
| 窗口首帧保留、DMA-BUF 显式同步及 GPU 裁切 | [window_stream.c](dmabuf/window_stream.c) · [unix_bridge.c](dmabuf/unix_bridge.c) · [composite.c](dmabuf/composite.c) |
| 独立前缀中的自有 Win32/GDI 探针 | [install_trial.py](install_trial.py) · [probe.cpp](probe.cpp) |

默认的应用内模式由 `inapp_actions.exe` 在授权后创建对应的透明占位窗。单独构建的 `felix-wgc-window.exe` 用于沿用固定标题的单来源试验。窗口和显示器通过不同的授权和通道关联。

## 隔离构建

PE 构建需要 Python 3、`pefile`、Docker，以及 [build.py](build.py) 固定摘要的 SteamRT4 SDK 镜像。输入是候选 Proton 自带的 x86-64 DXVK D3D11 模块。宿主构建需要 C 编译器、`pkg-config`、带同步时间线定义的 PipeWire/SPA 开发头文件、libdrm 与 Vulkan 开发文件、GLSL 编译器。可用 `GLSLANG_VALIDATOR` 指定 `glslangValidator` 或 `glslang`。运行 Portal 逻辑还需要 PyGObject 的 Gio/GLib、Python Xlib 和 GNOME ScreenCast Portal。通过 AT-SPI 读取所选标题需要可用的 AT-SPI GI 接口。

将 `source_dir` 指向本文件所在目录，将 `reference_runner` 指向一份已验证的 Proton。以下命令在独立目录构建并安装到测试前缀。

```bash
trial="$(mktemp -d "$PWD/.wgc-prototype-XXXXXX")"
cp -a --reflink=auto "$reference_runner" "$trial/runner"
wrapper="$HOME/.local/bin/shorin-proton-wrapper"
runner="$trial/runner/proton"
prefix="$trial/companion-prefix"
"$wrapper" --prefix "$prefix" --runner "$runner" --init

dxvk="$trial/runner/files/lib/wine/dxvk/x86_64-windows"
python3 -B "$source_dir/build.py" "$dxvk/d3d11.dll" "$trial" --in-app
sh "$source_dir/dmabuf/build.sh" "$trial/window-stream-interactive"
sh "$source_dir/dmabuf/build_layer.sh" "$trial/vulkan"
python3 -B "$source_dir/install_trial.py" "$trial" companion-prefix
```

已部署转发器的独立候选重新构建时，以原始的 `$dxvk/felix_d3d11_base.dll` 为导出输入。宿主 worker 支持把解包好的开发头文件目录作为第二个参数传给 `dmabuf/build.sh`。若在新的隔离前缀也要复测显示器，可额外构建 `"$trial/window-stream"`。现有安装的显示器 worker 和旧窗口 worker 分别维护。

转发器保留输入 DXVK 的具名导出及序号，将新增的两项 WinRT 桥接导出转到 `felix_wgc.dll`。测试安装脚本在隔离前缀注册三个 WinRT 类。PE 模块、Unix 桥接库与 worker 应使用匹配的源码构建。DXVK、SteamRT4 和运行器沿用各自的上游来源和许可证。

### 自有 Win32 探针

沿用以上构建，在同一个独立目录另建 `probe-prefix` 后可测试 GDI 与 D3D11 帧池。探针校验交替色、尺寸和关窗清理。它使用自有 Win32 窗口。

```bash
probe_prefix="$trial/probe-prefix"
"$wrapper" --prefix "$probe_prefix" --runner "$runner" --init
python3 -B "$source_dir/install_trial.py" "$trial" probe-prefix
probe="$probe_prefix/pfx/drive_c/felix-wgc-probe.exe"
cp "$trial/probe.exe" "$probe"
env FELIX_WGC_FIXTURE_TITLE="Felix WGC Smoke" WINEDLLOVERRIDES=d3d11=n \
  "$wrapper" --prefix "$probe_prefix" --runner "$runner" "$probe"
```

## 连接测试伴侣

先在测试前缀安装自己取得的 Windows 客户端，并将 `launcher` 指向该测试副本的官方启动程序。给同一次测试指定独立的运行目录，用实际 DRM render node 替代下面的示例。宿主 relay 当前要求只有一个可确定的 render node。

```bash
runtime="$(mktemp -d "$XDG_RUNTIME_DIR/felix-wgc.XXXXXX")"
render_node=/dev/dri/renderD128
unixlib="\\??\\Z:$(printf '%s' "$trial/vulkan/libfelixwgc.so" | tr '/' '\\')"

env FELIX_WGC_AUTO_DIR="$runtime" \
  FELIX_WGC_GPU_UNIXLIB="$unixlib" FELIX_WGC_GPU_RENDER_NODE="$render_node" \
  FELIX_WGC_FRAME_RATE=30 VK_ADD_LAYER_PATH="$trial/vulkan" \
  VK_INSTANCE_LAYERS=VK_LAYER_FELIX_wgc_dmabuf \
  PRESSURE_VESSEL_FILESYSTEMS_RW="$runtime" \
  WINEDLLOVERRIDES='d3d11=n;graphicscapture=n' \
  "$wrapper" --prefix "$prefix" --runner "$runner" "$launcher" \
  --force-renderer-accessibility=complete
```

主窗口出现后读取该测试窗口的 XWayland XID 和 Linux PID，例如用 `wmctrl -lp` 核对窗口和进程归属。将 `xid`、`pid` 指向同一测试窗口，将 `source_store` 指向该前缀的 `AppData/Roaming/webcast_mate/WBStore/sourceStore.json`。两个命令在各自终端使用同一组路径和运行目录。

```bash
FELIX_WGC_DYNAMIC_TITLE=1 python3 -B "$source_dir/inapp.py" \
  "$runtime" "$trial" "$pid" --source-store "$source_store" --parent-xid "$xid"
```

```bash
windows_runtime="Z:$(printf '%s' "$runtime" | tr '/' '\\')"
PRESSURE_VESSEL_FILESYSTEMS_RW="$runtime" \
  "$wrapper" --prefix "$prefix" --runner "$runner" \
  "$trial/inapp_actions.exe" "$windows_runtime"
```

在测试伴侣的空场景点「添加素材 → 窗口」，从 Ubuntu 列表先后授权两扇自有窗口。核对素材标题、两条预览和关闭或删除时的释放。测试结束后正常退出候选，结束它的辅助程序。现场安装的成套恢复流程见下方回退记录。

## 已验证范围与后续开发

独立候选完成双路取帧与取消复测。日常原 Dock 版完成系统列表、静止窗口首帧和删素材清理。源码归档保留已验证的选窗实现。授权后伴侣选择框可能短暂闪过，暂缓处理。

[选窗流程](../../docs/streaming/WINDOW_PICKER_FLOW.md) · [多窗口验证](../../docs/streaming/WINDOW_PICKER_MULTI_WINDOW.md) · [清理](../../docs/streaming/WINDOW_PICKER_CLEANUP.md) · [回退](../../docs/streaming/WINDOW_PICKER_ROLLBACK.md)

本项目新增代码由 Felix Li 在 OpenAI Codex 协助下完成，采用 [BSD-3-Clause](LICENSE)。
