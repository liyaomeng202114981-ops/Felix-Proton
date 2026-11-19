# 窗口采集的回退方法

以下步骤适用于已单独安装显式同步窗口采集进程的直播伴侣前缀。

已接入 Ubuntu 窗口列表与独立窗口帧通道的安装，先按对应批次恢复选窗组件。[新选窗修复的回退方法](WINDOW_PICKER_ROLLBACK.md)

## 恢复原窗口采集进程

1. 在 Ubuntu 停止当前窗口共享，确认该窗口的预览流已经结束。
2. 在该伴侣前缀的 `felix-runtime` 目录中，将 `window-stream-explicit-sync` 移入同一安装的备份目录。保留原文件供重新启用时恢复，原 `window-stream` 继续用于回退。
3. 在伴侣里重新打开「窗口」并授权测试窗。新的授权会话会选择原 `window-stream`。在预览里确认源已重新连接。原隐式同步路径在受测环境中可能复现后台黑帧。

需要重新启用修复时，先结束回退后的窗口流，将文件按原名放回 `felix-runtime`，再发起一次窗口授权并查看预览。主机的音频配置、代理或 DNS 不参与此回退。

## 临时改用整桌面

原 Dock 图标右键保留「UnityCapture 回退」。启动该项后，在伴侣中使用原来的 **Unity Video Capture** 摄像头素材。它使用整桌面共享范围，适合需要立即恢复画面时使用。

恢复窗口前核对场景和正在共享的素材，确认只使用需要的来源。

[黑屏原因与对照](WINDOW_BLACK_FRAMES.md) · [显式同步修复](DMABUF_EXPLICIT_SYNC.md) · [原 Dock 复测](WINDOW_DOCK_RETEST.md)
