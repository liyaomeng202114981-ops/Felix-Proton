# 窗口采集的 DMA-BUF 显式同步

修复应用在 Linux 宿主的窗口采集进程。它优先协商 PipeWire 的 `SPA_META_SyncTimeline`，同一帧携带一份 DMA-BUF 和两个时间线文件描述符。采集进程等待生产端的 acquire point 后，才把帧交给伴侣的 WGC 兼容层。消费端完成 Vulkan 提交并等待 GPU fence 后确认归还，采集进程才 signal release point。生产端随后可安全复用缓冲。[PipeWire 的 DMA-BUF 同步说明](https://docs.pipewire.org/1.4/page_dma_buf.html) · [Mutter 50.1 的生产端实现](https://github.com/GNOME/mutter/blob/50.1/src/backends/meta-screen-cast-stream-src.c#L771-L823)

## 协商与边界

- 渲染节点支持 DRM 同步对象时间线时，窗口进程提供显式同步选项。生产端只协商出单平面隐式同步时，沿用原协议。
- 已协商的时间线不合法、等待超时或归还失败时结束该流。成功归还由 GPU 完成确认驱动。
- 生产路径继续使用 DMA-BUF。诊断用的 RGB 采样和 MemFd 对照只用于定位。
- 现有本机集成按素材类型选择进程。窗口优先用 `window-stream-explicit-sync`，全屏继续走原 `window-stream`。PE 和 Unix 桥接库、声音、专属直连及 UnityCapture 回退沿用既有组件。

宿主进程使用 PipeWire、SPA、libdrm 和 Vulkan 开发依赖编译，通过 `-Wall -Wextra -Werror`。当前渲染节点完成了 DRM 同步对象的导入、时间线 signal 与 wait 往返。原 Dock 的实际窗口流记录了 `WINDOW_DMA_BUF_SYNC explicit`。

[黑屏原因与对照](WINDOW_BLACK_FRAMES.md) · [原 Dock 复测](WINDOW_DOCK_RETEST.md) · [回退方法](WINDOW_CAPTURE_ROLLBACK.md)
