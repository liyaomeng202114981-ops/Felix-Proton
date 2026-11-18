# Proton UI兼容性改进

## 窗口问题链与最终用户验收（2026-11-18）

[问题链与通用解决方案](UI_WINDOW_COMPATIBILITY.md)承接下方透明里程碑：输入区、窗口移动和辅助层WM状态已分层定位；另收录名称/图标的通用元数据方法。组合v7的白带、最大化下拖和贴边拖出均获用户实机复测通过。直播画面/声音/编码仍在[独立领域](STREAMING_COMPATIBILITY.md)维护。

| 本轮增量 | 结果 | 接入边界 |
| --- | --- | --- |
| 0068目标窗输入区域 | 自有复现/控制及相关回归比较通过 | 现有alpha模式下的Wine X11路径 |
| 0069标题栏原生移动 | 私有GNOME真实输入对照及组合版用户复测通过 | 默认关闭，按应用允许鼠标标题栏SC_MOVE，保留键盘/SC_SIZE守卫 |
| 0070辅助层CSD提示 | 同代实机因果对照、13类/7配置和新会话自动设置通过 | 精确Win32类+同进程owned装饰角色；GTK hint仅Mutter，不能全局套用所有Chromium类 |
| 通用交付 | 机制与源码可复用，合成样本和本机案例已验证 | 统一应用管理、跨桌面及完整发行构建尚未交付；不复制单独模块到任意Wine |

[0068报告](../../fixes/0068-composed-alpha-input/README.md) · [0069报告](../../fixes/0069-native-maximized-move/README.md) · [0070报告](../../fixes/0070-profiled-layered-csd/README.md) · [校验清单](UI_WINDOW_SOURCE_MANIFEST.json)。旧阶段描述按时间保留，最新状态以上述为准。

分类：UI与桌面显示。更新：2026-11-17。本项归入Felix-Proton自身的UI兼容改进；直播伴侣是此次定位和实机验证透明缺陷的案例。此次GitHub同步用于保存阶段成果及后续接续基线。

## 当前基线

| 工作 | 当前结果 | 尚未覆盖 |
| --- | --- | --- |
| 源像素透明度 | 0067保留跨进程客户端/离屏源DC的ARGB；自有样本和本机案例通过，用户确认黑底消失 | 通用完整构建、其他绘图路径、位数及工具包验证 |
| 宿主附加外框 | GNOME/RWC按实际Meta类名修正规则后，用户确认透明框消失 | 当前为整应用类级排除；通用helper-only及其他桌面未实现 |
| 通用接入 | 已完成分层评估和依赖核查，发现Wine/DXVK关闭语义不一致 | 按应用开关、输入/性能及完整队列验收；尚未实施 |

[里程碑](WINE_TRANSPARENCY.md) · [技术报告](../../fixes/0067-argb-other-process/README.md) · [验证范围](TRANSPARENCY_TEST_RESULTS.md) · [通用评估](WINE_TRANSPARENCY_INTEGRATION_ASSESSMENT.md) · [样本/输出](../../tests/argb_client_fixture/README.md) · [校验清单](TRANSPARENCY_SOURCE_MANIFEST.json)

已公开源码基线：[3b454a57](https://github.com/liyaomeng202114981-ops/Felix-Proton/commit/3b454a573bc1b407d26783b408213660ada09973)。现有Release没有升级为包含0067的新运行器；完整新构建尚未验收。

## 下一次从哪里继续

1. 先核对当前使用的运行器和配置，阅读上述报告/评估及公开源码清单；不把历史PID、窗口ID或本机候选状态当现态。
2. 如后续实施通用接入，先在独立目录完整构建匹配候选，保持默认行为；统一启停语义及目标进程树隔离，沿原入口按应用加载。
3. 核验真黑色/透明像素、输入、读回性能、不同绘图路径、相关Wine回归及回退。
4. 可选GNOME适配独立推进：实际窗口身份、主体/辅助窗角色及生命周期，不将所有透明窗口一律排除。

这些是待办建议，不是本次已执行或已批准的部署。既有其他客户端的问题及失败候选继续按各自记录保留，不能全部算作这次修复完成。

[返回项目分类目录](INDEX.md)。直播画面采集、声音和编码的进展见[直播研究](STREAMING_COMPATIBILITY.md)，分别验收。
