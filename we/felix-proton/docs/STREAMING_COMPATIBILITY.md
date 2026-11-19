# Ubuntu 上的抖音直播伴侣兼容记录

2026-11-18，用户在 Ubuntu 上用 Felix-Proton 运行 Windows 版抖音直播伴侣 13.3.5，经应用专属直连成功开播。媒体 SDK 在 16:13:48（北京时间）记录 RTMP 推流启动，在 16:14:20 记录停止。测试结束后，伴侣仍能显示桌面预览。

验证环境为 Ubuntu、GNOME Wayland、XWayland 及伴侣专用 Proton 前缀。保留官方 Launcher 与原桌面图标。画面经系统桌面采集和 UnityCapture 送入伴侣，声音使用已验证的系统回采路径。使用现有设备完成测试，无需外接采集卡。

| 专题 | 已验证结果 |
| --- | --- |
| [画面、声音与本地编码](streaming/AUDIO_VIDEO.md) | 桌面及游戏菜单能进入伴侣。实际 16.8 秒游戏菜单录像含 720p30 HEVC 和双声道 AAC，可完整解码 |
| [原图标重开与启动耗时](streaming/STARTUP_RECOVERY.md) | 修复退出后运行时残留导致旧会话被误认成已打开的问题。暖重开恢复主窗和桌面预览 |
| [开播失败、代理与 DNS 排查](streaming/PROXY_DNS.md) | 创建直播间曾被拒绝。实测应用绕开本机代理、直连两个业务域名，随后用户从 Ubuntu 成功开播 |
| [从 Ubuntu 列表选择窗口](#从-ubuntu-列表选择窗口) | 同一伴侣可以重复打开系统窗口列表，分别授权并预览不同窗口 |
| [窗口后台预览与 DMA-BUF 同步](#窗口后台黑屏修复) | 原 Dock 版的 Wayland 窗口被其他应用完全遮挡约 22 秒，伴侣预览持续更新 |
| [窗口显示与交互适配](UI_WINDOW_COMPATIBILITY.md) | 已公开的黑底、透明外框、名称图标和窗口还原修复记录 |

此前实播为单机短时验证，观众端音画质量、长时间推流和其他桌面环境仍待验收。桌面桥与启动控制器为本机原型。下述窗口后台复测独立于此前的整桌面实播。

## 窗口后台黑屏修复

2026-11-19，绕开伴侣直接采样 PipeWire 的窗口 DMA-BUF，复现了原隐式同步路径的黑帧样本。窗口采集改为等待生产端显式同步后，同一格式的对照样本没有出现黑帧。随后用原 Dock 版复测遮挡，伴侣画面持续更新。该轮只做本地预览。

| 专题 | 收录内容 |
| --- | --- |
| [黑屏原因](streaming/WINDOW_BLACK_FRAMES.md) | 进入伴侣前的 RGB 取样，以及隐式同步、显式同步和 MemFd 对照 |
| [DMA-BUF 显式同步修复](streaming/DMABUF_EXPLICIT_SYNC.md) | acquire point、GPU 完成确认和 release point |
| [原 Dock 复测结果](streaming/WINDOW_DOCK_RETEST.md) | 完全遮挡期间的取样与画面更新，以及验证范围 |
| [回退方法](streaming/WINDOW_CAPTURE_ROLLBACK.md) | 恢复原窗口进程、重新启用修复和 UnityCapture 回退 |

上述内容记录本机实现和验收，本次 GitHub 同步仅包含文档。

## 从 Ubuntu 列表选择窗口

2026-11-19，从直播伴侣点「添加素材 → 窗口」后可以直接进入 Ubuntu 窗口列表。选中的窗口由伴侣自动接成对应素材。用户已确认原 Dock 版选窗成功，本轮实测覆盖本地预览。

| 专题 | 收录内容 |
| --- | --- |
| [选窗流程](streaming/WINDOW_PICKER_FLOW.md) | 系统授权、标题、自动选入，以及暂缓处理的短暂闪过 |
| [多窗口验证](streaming/WINDOW_PICKER_MULTI_WINDOW.md) | 隔离版双路取帧，原 Dock 版列表与静止窗口首帧 |
| [取消、删除与关窗](streaming/WINDOW_PICKER_CLEANUP.md) | 各自授权的清理结果 |
| [组件回退](streaming/WINDOW_PICKER_ROLLBACK.md) | 恢复上一套组件及 UnityCapture 整桌面入口 |

[选窗源码、构建与隔离复跑](../src/wgc-compat/README.md)

[返回项目分类目录](INDEX.md)
