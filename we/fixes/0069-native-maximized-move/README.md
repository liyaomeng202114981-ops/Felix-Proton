# 0069：按应用允许原生窗口管理器处理最大化标题栏拖动

2026-11-17。Felix Li，使用 OpenAI Codex 协助。默认关闭的本地候选，未发行。

## 现象和根因

用户反馈直播伴侣贴边/最大化后不能像GNOME窗口一样向下拖出。0068针对输入区被局部绘图表面覆盖；另一个独立问题在`X11DRV_SysCommand()`：只要存在`WS_MAXIMIZE`，SC_MOVE和SC_SIZE都在发送EWMH请求前被拒绝；win32u后备移动路径也直接拒绝zoomed窗口。

私有GNOME50.1/XWayland的自有无边框Win32样本确认：正常状态可移动，最大化后接收到`WM_SYSCOMMAND 0xf012`，却保持1280×768。普通有装饰Wine窗口由Mutter标题栏处理，能恢复，说明WM本身具备该能力。不能把0068恢复标题区输入就当作本问题已解决。

## 修复

[补丁](../../../patches/wine/0069-winex11-Opt-in-to-native-maximized-caption-moves.patch)只修改`winex11.drv/window.c`。当且仅当`WINE_X11_NATIVE_MAXIMIZED_MOVE=1`，允许已有托管窗的鼠标标题栏SC_MOVE继续进入原有`_NET_WM_MOVERESIZE`路径，让WM负责拖动时的还原。

- 默认/0保持原分支；不按应用名或窗口标题硬编码。
- 仍要求whole window、managed、非withdrawn以及WM支持相应EWMH动作。
- 只允许鼠标`HTCAPTION`；键盘移动、SC_SIZE和其他hit仍保留最大化拒绝逻辑。
- 不自行伪造SW_RESTORE、窗口几何或Windows消息，不改变min/max尺寸约束。

这是本项目的应用级UI候选，不是所有WM的新默认；没有升级日常Steam/UU运行器。

## 预期行为与Windows边界

用户要求GNOME式从最大化/贴边状态拖出，现有WM已通过普通装饰窗对照提供这种行为。[Chromium窗口消息处理源码](https://chromium.googlesource.com/chromium/src/+/8a0dac94cf639d40c0c00557bf9eb5338ae82146/ui/views/win/hwnd_message_handler.cc)说明标题栏鼠标路径会形成SC_MOVE加0x0002，与实际自有样本消息相符。此次没有原生Windows实测；补丁是可选宿主集成，不能声称与所有Windows版本行为完全等价。

直播伴侣的正常UI有1080最小宽度，当前1920屏幕的一半是960。这个原应用约束可能使其不能精确占半屏，但不应拿它替代下拖还原验收，也不通过强行缩小/裁剪应用来掩盖。

## 验证及限制

[源码、私有桌面测试驱动与前后结果](../../tests/native_maximized_move/README.md)均为自有样本，无厂商文件、账号或真实桌面。输入只发往验证过PID/UID/私有HOME/runtime的headless GNOME总线，不使用宿主鼠标。

| 检查 | 开关关闭 | 开关开启 |
| --- | --- | --- |
| CSD普通移动 | 640×420保持，位置+36,+144 | 相同 |
| CSD最大化标题栏下拖 | 收到0xf012，保持1280×768 | 还原640×420并继续移动 |
| 贴左边与拖出 | 640×768→640×420 | 相同 |
| 最大化底角拖动 | 收到SC_SIZE，保持最大化及原几何 | 相同 |
| 普通装饰窗最大化下拖 | 能还原 | 能还原 |

两个完整矩阵及较早单项对照均退出，正式矩阵对应私有进程清理核对为空。普通装饰窗的普通态采样点没有形成有效拖动，不计其为正向移动对照；正向对照使用实际移动的CSD普通态。最初未等待WM稳定的普通态结果也保留而不计通过。

组合候选的Wine`user32 win`为77978断言、149todo、2skip、38失败；输入候选77979断言、同38条失败消息完全一致，无新增失败位置。该Xvfb没有EWMH WM，原生移动由前述GNOME实测补足，不称Wine测试全部通过。键盘路径仅静态核对，未实测；其他WM、Wine Wayland、i386 Unix、混合DPI、多屏、长期性能、真实客户端接受度和全队列构建仍未验收。

## 构建和来源

复制0068源码/对象，使用既有固定steamrt4 SDK断网只读容器仅重编x64 Unix模块，Werror通过；新runner与0068版比较6229个常规文件，仅winex11.so不同。渲染`init.c`与0068测试源逐字相同，没有热改正在使用的二进制。

- SDK：`registry.gitlab.steamos.cloud/proton/steamrt4/sdk/x86_64@sha256:6c1789cad862fd8ed9d46d71bbf8752bb7cb2336ab5e9680c0f0e3e7c88d77f1`。
- window.c输入SHA256：`47446670d795cd59a15eecd3c99c921228a439630adf7dad2174a61f7873afd1`。
- 测试源SHA256：`22a5df33aeb8510532badfcb6ffb24f5816cd3f87cafb0d39a3a60338f8256b0`。
- 模块SHA256：`38d39dd9b4f43418a706c72f10c6e9c9e0aa1944e1251f998e2aba33e3165f2f`。
- 局部诊断输入快照4844710d后提交`aec614b25e0b7dca1c8851082b49f908dd896d24`并format-patch，补丁可精确重建测试源。这不是重建上游完整Git历史；原作者/许可保持。

## 实机接入与回退

曾在伴侣私有启动器和controller中选择独立`runner-input-move-v2`并启用1，现已全部退回原alpha-v2/启动脚本。后续组合版、原版、硬软UI和独立userdata等均在窗口定位MonitorFromWindow=NULL断言退出；主会话GNOME physical=0/logical=0、XRandR/Xinerama无输出，Win32探针也无有效HMONITOR，故不能将当前启动失败单独归因本补丁。等待用户恢复显示器或说明无屏场景，实机下拖未验收。

官方自动更新的13.3.5及新Launcher/config已保留，原版13.2.5的3627文件/3460资源复核后恢复原路径组合，原35份素材/声音设置SHA保持。试验UseXRandR=N无效已删回原absence；未改宿主显示配置或重启桌面。共享曾clean Closed，后续仅自有synthetic测试图，最终停止专用app/producer/feeder；没有恢复桌面共享、录制或开播。

同目录`local_session.before-native-move.py`和`launch_desktop.before-native-move.py`备份可退回0068；更早`local_session.before-composed-input.py`可退回0067基线。先退出精确专用应用会话，按私有安装账本SHA恢复两启动文件再重开，不热替换模块。是否恢复桌面共享按用户最新选择单独处理，不用过期token或旧运行状态代替。


## 2026-11-18 组合版实机用户验收补充

后续含0067/0068/0069及0070的专用CSD v7已在本机选用。用户先确认顶部白带不再出现，
再明确“最大化下拖和贴边拖出也都正常了”。据此两项还原交互的组合版实机用户验收通过；
不是将每个补丁分别做了新一轮真实客户端因果隔离。此前阶段的“待验”描述保留为历史，
当前验证及回退见[0070报告](../0070-profiled-layered-csd/README.md)。
还原尺寸约8×10漂移及应用最小宽度边界未在本次重测或修复，其他WM、多屏/DPI、
长期稳定性和完整发行构建仍未验证；本轮仅记录用户反馈，没有运行器/配置改动或开播。
