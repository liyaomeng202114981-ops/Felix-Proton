# 0068：子绘图表面错误替换整个父窗输入区域

2026-11-17。Felix Li，使用 OpenAI Codex 协助。本地候选，未发布或安装到日常共享运行器。

## 现象与范围

在直播伴侣的贴边/最大化拖动问题中，发现实际主窗画面是不透明的，但X11输入区只剩中间预览矩形，标题区四个点均无法接收输入。此缺陷会影响主窗操作；它是否完整解释最大化拖动还原，还需在实际画面启用时单独验收，不能把静态输入区恢复当作拖动已通过。

自有GDI父窗＋D3D11子窗在断网私有Xvfb复现：692×446父窗仅剩(120,150)处320×180子窗可接收输入，其余三个不透明点被排除。候选恢复四个点，父窗RGBA控制值保持。

## 根因与修复

既有alpha模式在每个client surface呈现时读取该surface，再把结果作为整个toplevel的ShapeInput。独立子surface只能描述局部内容，不能替代父窗的完整输入区域。

[补丁](../../../patches/wine/0068-winex11-Derive-alpha-input-shapes-from-composed-destination.patch)仅修改`winex11.drv/init.c`：alpha模式先完成blit，再按完整目标窗的几何、零原点和实际visual读回，计算ShapeInput。MIT-SHM与fallback使用同一个目标drawable。旧luma/ShapeBounding路径仍先采样再决定blit，未启用alpha时保持原分支；没有删除透明尾部或抠掉黑色。

需要现有`WINE_LAYERED_OVERLAY_ALPHA=1`及0067等前置，不是新的全局默认。已有分层绘图/输入功能属于上游；本次只修局部surface覆盖父窗输入的错误，继承Wine文件许可。

## Windows 预期和限制

父窗中有一个独立绘图子窗，不应导致其他父窗控件失去输入。预期由同一样本的完整不透明像素、父窗/子窗几何以及关闭输入采样的对照支持。没有原生Windows成对运行，不声称Windows实测通过。

完整目标窗读回仍继承既有X11读回边界。Xlib说明被遮挡或形状外的区域不一定有有效内容；不能用完全shaped-out辅助窗的存储alpha判断实际黑底，也不能仅看ShapeInput而忽略与Bounding Shape的有效交集。参见[Xlib图像读取规范](https://www.x.org/releases/X11R7.6/doc/libX11/specs/libX11/libX11.html)。原生Wine Wayland、其他桌面、多屏缩放、独立i386 Unix模块、性能/长时负载及完整补丁队列构建未验收。

## 验证

[自有源码及前后输出](../../tests/composed_alpha_input/README.md)不含厂商代码、账号、真实桌面或二进制。

| 检查 | 结果 |
| --- | --- |
| GDI父窗＋DXVK/D3D11子窗 | 基线三个父窗点false、子窗点true；候选四点true，父窗RGBA控制值保持。软件Vulkan，非宿主GPU或原生拖动测试 |
| Electron36.4.0三种窗口 | 不透明控制、透明owned窗与透明popup的尾部/灰卡/真黑RGBA控制值保持 |
| 全透明mapped辅助窗 | 两版72000像素alpha0、输入区均为空；先show再ignore-mouse的独立样本 |
| GDI/ULW回归 | 两窗完整RGBA像素SHA前后一致 |
| Wine user32 win | 基线77978、候选77979断言；同38条既有失败，149todo、2skip，失败消息逐条完全一致。不是全部通过 |
| 隔离清理 | 上述10个正式case全部cleanup_ok；额外无效空白样本也全部清理 |
| 实际客户端 | 只在专用controller选择独立候选，原Launcher/alpha/NVENC/摄像头/声音选择保持。重开时素材已隐藏，切换前也是如此；必须恢复预览后再验输入与拖动，目前等待用户。不开播 |

固定SDK为`registry.gitlab.steamos.cloud/proton/steamrt4/sdk/x86_64@sha256:6c1789cad862fd8ed9d46d71bbf8752bb7cb2336ab5e9680c0f0e3e7c88d77f1`，断网只读容器编译生产模块，Werror通过。复制源码/对象与runner后构建，不运行会重置子模块的脚本、不热改在用二进制。6229个常规运行文件比较仅`files/lib/wine/x86_64-unix/winex11.so`不同。

- 输入源SHA256：`9a822340693b151636d473a60c09b3cc2da229a0cc1fef7c7719104e110a05d7`。
- 测试源SHA256：`442ea8ec85178771a149b97d932efbba18f26b08bf75911310c48a9a96c4a36d`。
- 模块SHA256：`67fc9b0e5f0b84bc5b7127fceeaef4c47efe5fad884ca4ec49093e88151396b8`。
- 源提交`d7a616507d8de7a919ddb5280dc0bde90708e4fe`接在0067诊断快照提交后；该Git只跟踪部分诊断源，不伪称完整上游历史。format-patch应用到保存的v2源可精确重建测试源。

## 排除方案与失败记录

1. 现成`WINE_LAYERED_OVERLAY_INPUT_SHAPE=0`恢复主窗输入，但实际透明helper获得全输入，拒绝并精确回退；不全局关闭alpha。
2. 初始普通平面Electron对照没有复现子surface问题，错误预期断言失败如实保留；另建GDI＋D3D11子窗后得到真正前后复现。
3. 第一组空白canvas出现滚动条，不能算全透明；后续pre-show ignore-mouse样本在Wine未映射。修正为先显示再ignore后，mapped全透明对照通过；所有失败及清理记录保留。
4. 实际只读前缀路径过滤最初没有归一化末尾斜杠，空列表不是没有窗口；修正Path.resolve后才取正式证据。
5. 最大化SC_MOVE仍有独立拒绝分支；未靠静态猜测删除该限制。实际拖动若仍失败，需要独立定位及候选。

## 回退与当前状态

原alpha-v2 runner完整保留。本阶段曾仅将伴侣私有`native-av/local_session.py`的runner和验证manifest改为新候选（现已撤回，见下方现态），同目录`local_session.before-composed-input.py`保留原控制器。回退先正常结束这个专用会话，核对备份SHA后恢复控制器并重新start；不得热替换模块。原名称/图标、RWC规则、Steam/UU和日常共享运行器不属于本补丁变更。

当前结论为局部surface输入缺陷的隔离修复通过，实际预览启用后的贴边/最大化拖动待验；不称整个问题3完成。

后续现态修正：组合0068/0069及原alpha-v2等启动对照均遇到窗口定位时MonitorFromWindow=NULL；主GNOME会话physical=0/logical=0、XRandR无输出，自有Win32探针也无有效句柄。当前已退回原alpha-v2/controller并停止专用临时会话，等待显示器恢复，不能归因为某一候选。更新后的13.3.5及启动器已备份，原版13.2.5组合恢复，原35份素材/声音等设置SHA保持；无效UseXRandR试配已撤销，没有重启宿主或恢复桌面共享。


## 2026-11-18 组合版实机用户验收补充

后续含0067/0068/0069及0070的专用CSD v7已在本机选用。用户先确认顶部白带不再出现，
再明确“最大化下拖和贴边拖出也都正常了”。据此两项还原交互的组合版实机用户验收通过；
不是将每个补丁分别做了新一轮真实客户端因果隔离。此前阶段的“待验”描述保留为历史，
当前验证及回退见[0070报告](../0070-profiled-layered-csd/README.md)。
还原尺寸约8×10漂移及应用最小宽度边界未在本次重测或修复，其他WM、多屏/DPI、
长期稳定性和完整发行构建仍未验证；本轮仅记录用户反馈，没有运行器/配置改动或开播。
