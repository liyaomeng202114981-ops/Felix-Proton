# 0070：防止指定透明装饰辅助窗被误判为全屏

2026-11-18。Felix Li，使用 OpenAI Codex 协助。默认关闭的本地候选，未发行。

## 现象与根因

直播伴侣最大化后，主窗位于工作区 `[0,29,1920,1051]`，只带最大化状态；
同进程 owned 透明辅助窗却覆盖整屏并带 FULLSCREEN，导致 GNOME 顶栏隐藏，
主窗上方留下背景空条。该辅助窗的有效 Bounding/Input 交集为零。
这与 0067 修复像素 alpha、RWC 排除外框、0068 输入区和 0069 下拖路径分别相关，
不能用一次静态截图代替各项验收。

真实短时 x11drv 日志确认：Wine 请求的状态只有 `0x40`（SKIP_TASKBAR），
WM 却回添为 `0x42`。因此仅阻止 Wine 发送 FULLSCREEN 仍不够。
[Mutter 50.1 的整屏 ConfigureRequest 兼容逻辑](https://github.com/GNOME/mutter/blob/50.1/src/x11/window-x11.c#L2690)
在缺少自绘 frame 元数据时还会主动推断全屏。
[`_GTK_FRAME_EXTENTS` 解析](https://github.com/GNOME/mutter/blob/50.1/src/x11/window-props.c#L340)
接受四个 CARDINAL 零值，声明客户端处理边框。

在同一真实进程及窗口代中，仅增删辅助窗的该属性，四轮普通态→最大化的
FULLSCREEN 采样分别为 **59/61 → 0/61 → 58/61 → 0/61**。
每次移除已有全屏状态后，是否重新被 WM 加回与该属性一致。
主窗工作区、透明像素和已有预览链保持，构成实机可逆因果对照。
这是 Mutter 策略的兼容处理，没有原生 Windows 实测；不能声称所有 Windows
辅助窗都应如此，也没有修改宿主 WM 全局选项。

## 修复范围

[补丁](../../../patches/wine/0070-winex11-Keep-profiled-layered-decoration-windows-out-of-fullscreen.patch)
只更改 `winex11.drv` 的 `window.c`、`x11drv.h`、`x11drv_main.c`。
必须同时指定 `WINE_X11_NO_FULLSCREEN_LAYERED_HELPER=1` 和
`WINE_X11_NO_FULLSCREEN_HELPER_CLASS` 的精确 UTF-8 **Win32 类名**。
这不是应用标题或 X11 WM_CLASS 匹配；不能全局给所有 Chromium 类程序启用。

- 角色须为同进程 captioned 顶层 owner 的 owned 窗，带 LAYERED/TRANSPARENT，
  不带 APPWINDOW、CHILD、CAPTION、THICKFRAME 或 MAXIMIZE。
- 对这个明确声明的装饰角色抑制 Wine 的几何全屏推断。
- 仅在 Mutter 下，于 WM hints 初始化及发送几何前补零 GTK frame extents；
  任何既有属性均保留，不写主窗，不改变其他程序、像素或输入区域。
- 每个 native X 窗只检查一次，销毁时重置缓存。缺失/错误开关或类保持旧行为。

该角色声明包含普通和最大化 owner，避免依赖 owner 状态同步时序。
应用若用相同角色承载真实全屏内容，不应采用此 profile。

## 验证与未完成项

[自有夹具、隔离驱动和前后输出](../../tests/layered_helper_fullscreen/README.md)：
13 类 × 7 配置通过；六种装饰角色获得零 frame hint 且不再全屏，七种守卫保持。
全部 owner 无新增 GTK 属性；已有 `[2,3,4,5]` 在转为 owned 并改几何后仍保留。
默认、0、2、缺类、错类与旧 runner 一致。测试不使用真实账户或宿主输入。

Wine `user32 win` 为 77,978 断言、149 todo、2 skip、38 失败，前后逐条相同；
不是全部通过。独立 SDK Werror 单模块构建通过；6,229 个 runner 常规文件只
`winex11.so` 改变。补丁重建的三个源文件与实际构建输入 SHA256 一致。

新会话已在本机专用 controller 选用 v7，无手工属性注入；首次最大化 61 次采样
辅助窗全屏计数为零，自动拥有零 frame hint，顶栏、标题及真实桌面预览可见。
用户先回复“不再出现了”，随后明确“最大化下拖和贴边拖出也都正常了”。
**组合v7的顶部白带、最大化下拖和贴边拖出均按用户实机复测通过归档**。
本次是用户体验验收补齐，不是对0068/0069/0070分别重新做实机因果隔离。
此前白带失败截图保留；本次没有取得白带
同步桌面/原始窗口对照，不能补记其独立机制已完全确定或长期稳定性已验证。
普通态每次还原尺寸约增加 8×10、应用最小宽度 1080 超过当前半屏 960 也未修复。
未做新录制、声音/编码信号测试或开播。

其他 WM、Wine Wayland、i386 Unix、多屏/混合 DPI、长期运行和完整发行构建未验证。
原入口/图标、RWC/BMS、两路声音端点和格式、默认音频及宿主路由保持；
应用重开改写了部分 WBStore 文件，不能声称所有设置文件字节不变。

## 排查过程与回退

先前 v3/v5 只抑制 Wine 状态推断，隔离样本通过却在实机失败。
v4 异步 owner 同步候选反向对照未通过；v6 的创建后样式时序样本未复现
旧版反例，未实机安装。均未导出为正式修复，不能把这些假设当作根因。
第一次实机诊断目标 HIDDEN 无效，第二次验证可见后才取得上述证据。
最初白块的 damage/空 Bounding 试验无效并已撤回；之后还原/最大化消除白块，
但用户再次截图复现，故当时继续保留失败状态；该历史阶段不与v7后的用户复测混淆。

当前为应用级独立 runner，无全局安装、热改或 GitHub 发布。
回退在正常停止精确专用会话后，按 SHA 账本恢复 controller 的 v5 备份；
也可按前阶段备份退回 0068+0069 或原 0067。v5 本身仍有全屏误判，
不能把回退称为显示问题已修复。每次重开须发现新 PID/窗口代和桌面源。

## 来源

保留 Wine/WE-Proton 上游历史和 LGPL 版权。局部诊断仓库包含原始三个文件快照，
不是完整 Wine 历史；仅导出实际代码提交 `10dc495ed956ce38d64d694f7aa31da4b1e4cabb`，
作者 Felix Li，含 OpenAI Codex trailer；不导出诊断快照提交。

- SDK：`registry.gitlab.steamos.cloud/proton/steamrt4/sdk/x86_64@sha256:6c1789cad862fd8ed9d46d71bbf8752bb7cb2336ab5e9680c0f0e3e7c88d77f1`。
- 模块 SHA256：`02c018584e0d35b2fa50cff70a21d61a6ca2a8b0920a008a74e1618eb3d14df9`。
- window.c SHA256：`748240b6c9307686a3b146c84185515cbb910b0c0e741945431d7063b01eee96`。
- x11drv.h SHA256：`459e35a93200a83853715137dfdb98832bb39ae4998b0496e83e08c2866eb659`。
- x11drv_main.c SHA256：`9485cc47f0e5008245b6eaad98a3fb5fdcebd7c27eeb88348be5ab781c4ad5a7`。

真实桌面、账号画面、配置及日志仅存本机忽略证据目录，不随源码导出。
