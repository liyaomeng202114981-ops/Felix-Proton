# 透明修复通用接入评估

分类：[Proton UI兼容性改进](UI_COMPATIBILITY.md) · [项目分类目录](INDEX.md)。阶段成果与待办分别记录，供后续继续开发。

2026-11-17，Felix Li，with OpenAI Codex assistance。用户要求先评估、保留现有配置，本节是建议与未来交付门槛，不是已批准实施或已交付功能。

## 结论与建议结构

可以纳入Felix-Proton，供通过匹配运行器启动的其他Wine程序按需使用。建议分为Wine绘图修复、按应用启用、可选桌面适配三部分。默认保持原行为，沿用原图标/入口加载已验证的应用规则，不要求逐款游戏填写启动参数。

| 部分 | 当前基础 | 剩余工作 |
| --- | --- | --- |
| Wine核心 | 0067没有伴侣专属类名/尺寸判断，自有样本复现并验证同一缺陷 | 匹配源码的完整队列构建、按应用开关及其他路径回归 |
| 应用策略 | Proton和wrapper可传递目标环境；本地关联原型已有合并/冲突检查，本轮未公开该原型 | 明确默认、用户选择和规则优先级，增加删除变量及目标进程树隔离 |
| GNOME外框 | RWC按Meta实际类名匹配，当前应用级排除有效 | 可选组件及helper-only角色/生命周期接口；避免取消其他应用主体效果 |
| 其他环境 | 核心和宿主可以解耦 | 原生Wine Wayland、其他合成器及独立i386 Unix路径需分别适配/验收 |

此方案指同路径程序在Felix-Proton中的复用。不能把当前winex11.so复制进任意发行版Wine；ABI、基础补丁和配套图形组件必须匹配。

## 构建依赖与静态核查

现有[准备脚本](../../../patches/protonprep-valve-staging.sh)先应用GE的[分层覆盖补丁](../../../patches/game-patches/layered-overlay-wine.patch)，再应用DW（含[0106](../../../patches/dwproton/0106-winex11-Implement-drawing-onto-ARGB-windows-of-other.patch)），最后WE（含[0067](../../../patches/wine/0067-winex11-Preserve-opt-in-ARGB-formats-for-other-process-surfaces.patch)）。0106的init.c后像与0067及已验证原输入的Git blob前缀81f3a0bc130一致。

0106已修复目标DC读取other-process visual，0067补齐源DC及临时客户端窗口。它是明确依赖底座的增量，不是适用于任意Wine版本的独立补丁。本轮只读核查，没有执行会重置子模块的准备脚本，没有完整队列构建或安装。

## 不能直接全局开启的原因

现有WINE_LAYERED_OVERLAY_ALPHA模式除了保留alpha，还会为进程顶层窗/部分客户端选择ARGB，改变部分offscreen与输入Shape路径，并通过[DXVK补丁](../../../patches/dxvk/layered-overlay-dxvk.patch)选择非不透明Vulkan compositeAlpha。默认输入区域采样还涉及窗口图像读回和扫描，存在交互及性能验证需求。将0067加入源码与给所有程序设alpha=1是不同变更。

另有实际关闭语义差异：Wine用atoi，值0为false；DXVK以字符串非空判断，字符串"0"仍进入透明分支。这是静态源码事实，未做新的视觉复现。接入入口应在目标进程环境中统一启停，关闭时删除该变量，不能只写0。现有关联合并能力不足以代表完整关闭；若改底层解析，要同时验证Wine/DXVK及1/2混合模式，不静默改变已有配置。

Proton的[官方配置说明](https://github.com/ValveSoftware/Proton#runtime-config-options)提供按应用运行时覆盖及通常的0关闭约定；本地自定义变量不能未经核对就套用该约定。环境在Wine进程内缓存，切换在目标应用下次正常启动生效，不能承诺热切换。

## 宿主适配范围

[RWC源码](https://github.com/flexagoon/rounded-window-corners/blob/b2cf6ec24ae6d32483f3938cb77a5b3672962282/src/manager/utils.ts)按win.wmClass精确匹配并自行绘制效果。Wine补丁不能自动控制所有GNOME扩展或其他桌面的阴影。

建议可选宿主组件核对实际Meta类名、RWC版本和黑/白名单语义；应用整类排除要明示对主窗效果的影响。helper-only策略需要逐窗角色、身份、actor代次和生命周期检查，不把所有透明窗都当成阴影，不靠修改所有已映射窗口WM_CLASS推广已有窄范围例外。无RWC时跳过该层，其他桌面独立提供能力；失效时保留应用绘图及其他用户设置。

不把图形开关与已有profile里的fsync、输入、Xalia或Wayland选择捆绑为通用默认。不自动改GNOME全局配置，不隐藏/裁切窗口或抠黑，不修改输入和焦点来掩盖视觉问题。Wine修复本身也不应绑定伴侣专用摄像头、声音或IPC方案。

## 建议推进顺序与未来门槛

先在独立源码/构建目录生成默认保持原行为的新候选和能力/来源清单，再沿现有入口提供按应用选择；不覆盖当前运行器/前缀/Steam或UU选择。绘图层验证后，再单独推进可选宿主组件和其他后端。第一阶段增量较小，主要成本在完整构建、输入和跨应用验证；通用宿主角色接口的工作量更高。

以下均为未来门槛，本轮没有执行：

- 默认关闭、未设置/0/1/2解析、目标进程树隔离及off→on→off冷启动回退。
- alpha0/低alpha/渐变、真正黑色、普通不透明窗、恒定alpha/颜色键、GDI/ULW和非矩形Shape。
- 自有Electron/DXVK基准之外的CEF/WebView2、Qt等样本；OpenGL/Vulkan/D3D12与PE32/WoW64分开验证。
- 点击/透明区输入、托盘/恢复、动态layered切换、最大化/全屏、DPI与多屏。
- RWC存在/不存在、黑/白名单、主窗/辅助窗、身份复用、并发设置变化和扩展故障回退。
- 1080p/4K、多透明窗的读回/扫描开销、CPU/GPU及帧延迟。
- 相关Wine conformance旧/新逐项比较，安装/模块匹配/回退和原日常能力验证；不把既有38失败称为全部通过。

本轮没有实施上述方案，也没有运行真实游戏、账号或反作弊探针。现有配置/服务身份、默认声音与IPv4规则/路由前后摘要一致。当前结论支持继续准备独立候选，尚不足以全局部署、承诺所有Wine程序兼容或改写既有Release。
