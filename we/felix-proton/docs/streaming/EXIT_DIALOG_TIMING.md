# 退出确认框分段计时

2026-11-19，在隔离伴侣会话中测量从发出关闭请求到收到完整退出确认框画面的耗时。将 Wine 事件、Chromium 跟踪中的 Windows QPC 时间、X11 原始窗口采样和 Mutter 区域帧接收时间对齐到同一主机的单调时钟。[Wine 的 X11 窗口实现](https://github.com/wine-mirror/wine/blob/master/dlls/winex11.drv/window.c) · [Mutter 区域采样接口](https://raw.githubusercontent.com/GNOME/mutter/50.1/data/dbus-interfaces/org.gnome.Mutter.ScreenCast.xml)

## Win32 窗口与 Chromium

在一轮可直接关联的追踪中，Wine 已在操作前约 13.38 秒持有同一 Win32 窗口。发出关闭请求后 65.4 毫秒，该 HWND 对应的 X11 窗口 ID 更换。匹配 280×162 区域的 Chromium 首次 `Paint` 在 67.81 毫秒。同一页面的 `firstPaint` 在 72.73 毫秒，`firstContentfulPaint` 在 96.23 毫秒。

## X11 映射、内容稳定和合成帧

以下统计取自另外四轮完整的联合采样，单位为毫秒。

| 采样边界 | 范围 | 中位数 |
| --- | ---: | ---: |
| 关闭请求 → 首次检测到 X11 已映射 | 18.7–53.0 | 25.9 |
| X11 映射 → 原始画面首次同时满足深色面板和红色按钮 | 55.5–110.3 | 81.5 |
| 首个符合条件的原始样本 → 首个恢复显示后的 X11 样本 | 25.3–39.9 | 33.3 |
| 首个恢复显示后的 X11 样本 → 收到对应的 Mutter 合成区域帧 | 8.1–24.3 | 17.0 |
| 关闭请求 → 收到完整的 Mutter 合成区域帧 | 139.7–183.0 | 163.9 |

这四轮中，映射后等到面板和按钮完整出现的区间最长，采样粒度不足以把整段归到 Chromium 或 Wine 的单一内部操作。稳定判定和轮询也计入恢复显示的时间。Mutter 的末段包含区域帧传输与接收，中位采样间隔约 19 毫秒，物理扫描输出未测量。Chromium 单轮事件属于独立样本。

[白底修复及原 Dock 复测](EXIT_DIALOG_WHITE_BACKGROUND.md) · [24 与 12 毫秒对照](EXIT_DIALOG_SETTLE_AB.md) · [独立的 8 秒超时异常](EXIT_DIALOG_TIMEOUT.md)
