# 直播伴侣的 Ubuntu 窗口选择流程

2026-11-19，原 Dock 入口的直播伴侣接入了 Ubuntu 系统窗口列表。旧下拉框可能只显示上次授权留下的 Win32 占位项，已有窗口共享运行时，后续窗口请求还可能被丢弃。

## 日常操作

1. 从原 Dock 图标打开直播伴侣。
2. 点「添加素材 → 窗口」，等待 Ubuntu 窗口列表出现。
3. 选中要共享的窗口，点「共享」。伴侣自动添加对应的「窗口」素材并显示预览。
4. 要添加另一扇窗口时，重复以上选窗步骤。每次授权各自关联一个素材，已有素材仍绑定各自的画面。

## 授权与素材绑定

伴侣打开自己的选择框时，兼容层先收起该窗口，发起一次窗口类型的 XDG ScreenCast 请求。Ubuntu 列出系统允许共享的窗口，由用户确认授权。选中的窗口有独立的 PipeWire 流和 DMA-BUF 帧通道。兼容层在授权后为它创建专用的透明 Win32 占位项，伴侣通过 WGC 接收对应画面。能取得系统选中项标题时沿用完整标题，标题无法确定时显示「Ubuntu 窗口」。[XDG ScreenCast 会话流程](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.ScreenCast.html#session-lifecycle)

## 已知界面现象

点共享后，伴侣自己的选择框可能短暂闪过。兼容层会重新显示这个框来自动选入已授权窗口，收到首帧后随即关闭。用户已确认选窗成功，并决定暂缓这项界面细节。闪过的频率和时长暂无专门测量。

[选窗辅助程序](../../src/wgc-compat/inapp_actions.cpp) · [Ubuntu 授权接口](../../src/wayland-capture/portal.py) · [源码入口与构建](../../src/wgc-compat/README.md)

[多窗口验证](WINDOW_PICKER_MULTI_WINDOW.md) · [关闭与清理](WINDOW_PICKER_CLEANUP.md) · [回退方法](WINDOW_PICKER_ROLLBACK.md)
