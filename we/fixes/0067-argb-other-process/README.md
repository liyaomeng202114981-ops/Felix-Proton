# 0067：跨进程 GPU 客户端丢失 ARGB 透明度

2026-11-17。Felix Li，使用 OpenAI Codex 协助。本次公开源码候选和复现结果；修复运行器尚未发行或合并到日常版本。

## 现象与依据

在 Ubuntu GNOME Wayland/XWayland 上运行抖音直播伴侣13.2.5时，菜单内容已加载，但辅助窗显示1280×720纯黑矩形；270×807工具窗的内容只有约404px，剩余部分也是黑色。它们原本是透明浮窗。只启用既有 `WINE_LAYERED_OVERLAY_ALPHA=1` 后，顶层窗虽变成32bit，空白像素仍是alpha255。

自有、无账号的 Electron36.4.0 样本复现相同现象：GPU进程绘制普通不透明控制窗、透明owned覆盖窗及透明菜单。两个透明窗尾部本应alpha0，基线却是 `[0,0,0,255]`。软件绘制对照可保留透明；GDI/UpdateLayeredWindow也正常，因此不能把所有路径都当作分层窗刷新问题。

## 根因与修改

GE/WE已有alpha开关选择了ARGB visual，但 `x11drv_client_surface_create()` 的other-process分支仍使用default visual/depth/colormap。GPU进程与窗口拥有者分离时会走这条路径。另一个遗漏在 `client_surface_update_offscreen()`：源DC把visual传为NULL，按默认RGB XRender格式读取，透明度被补成不透明。

[补丁](../../../patches/wine/0067-winex11-Preserve-opt-in-ARGB-formats-for-other-process-surfaces.patch)只修改 `dlls/winex11.drv/init.c`：保存实际drawable的visual；在现有alpha开关启用时，跨进程窗口使用所选visual及colormap，离屏源DC使用实际visual。不启用开关时保持原分支。不改变应用窗口大小、输入区域、颜色键或厂商文件，也不对DWM接口填假成功。

已有分层覆盖支持属于Wine及GE/DW/WE上游贡献；本补丁仅补齐跨进程窗口及源DC格式两处遗漏，继承被修改Wine文件的许可。

## Windows 行为与未验证部分

[Electron官方文档](https://www.electronjs.org/docs/latest/tutorial/custom-window-styles)说明 `transparent:true` 支持透明窗，透明HTML背景不能被转换成不透明黑。预期像素还由同一自有样本的软件路径及GDI/ULW控制组支持。本轮没有原生Windows机器成对测试，不能声称Windows实测通过。

范围限于X11/XWayland、既有alpha开关、测试过的64位Unix驱动。没有验证独立i386 Unix驱动、原生Wine Wayland路径、多屏缩放、全部透明应用或长时间负载。

## 构建与来源

- 匹配已安装候选的源码基点为 `28db1f7cd049a6f6e4be9fb5f8ce275868b7a4bb`；诊断副本另含完成端口修复。独立复制源码/对象目录后，仅构建 `dlls/winex11.drv/winex11.so`，没有运行会重置子模块的准备脚本。
- SDK：`registry.gitlab.steamos.cloud/proton/steamrt4/sdk/x86_64@sha256:6c1789cad862fd8ed9d46d71bbf8752bb7cb2336ab5e9680c0f0e3e7c88d77f1`。通过wrapper/SLR4运行，不裸跑host Proton。
- 原始 `init.c` SHA256：`5298f5afb8e17e799167eba29283acdad2d478ee7766c516e542c22ab03aa2c3`；测试后：`9a822340693b151636d473a60c09b3cc2da229a0cc1fef7c7719104e110a05d7`。
- 诊断Git仅有部分跟踪历史，明确创建匹配原输入快照 `d4fdc129983f03496a675e6f83e71d14c3727dcb`，再提交修改 `de8975e8a2184838c5cef93c82729462513898b8` 并 `git format-patch`；没有伪称完整Wine上游提交链。原源码副本未改写。
- 新模块SHA256：`6c0d062d00fe5e53d2587057085c236544d61edbf2fb1318d089728f49830add`。独立runner与原IPC候选共比较6668个运行代码文件，仅此模块不同。未热改安装中或使用中的二进制；尚未进行当前整个补丁队列的完整重建。

## 验证

[自有复现源码与前后输出](../../tests/argb_client_fixture/README.md)均不含厂商文件、账号或真实桌面。

| 检查 | 结果 |
| --- | --- |
| Electron36.4.0/DXVK，断网私有Xvfb+软件Vulkan | 基线两个尾部alpha255；v2稳态尾部alpha0。灰面板 `[51,51,51,255]`、真实黑方块 `[0,0,0,255]`、不透明控制窗 `[34,85,119,255]` 均保留，排除把黑色抠除的伪修复 |
| 普通GDI与ULW | 两个窗RGBA SHA与原版完全相同；透明边距/不透明内容正确 |
| Wine `user32_test.exe win` | 基线77982、候选77983项断言，均38个既有失败位置、149todo、2skip。37条失败消息相同；同一 `win.c:3736` 前台/焦点断言的返回值分别NULL/另一HWND，差异保留，没有新增失败位置。不是全部通过 |
| 实际伴侣 | 原Launcher/默认硬件UI加载新模块；辅助窗921600像素全alpha0，工具底100行alpha0，真实桌面预览可见。两路音频采集配置及默认设备保持；用户要求暂停声音/录制复测，未重验音频端到端或推流 |
| 宿主残留透明框 | 修复像素后仍有全窗大小的透明外框。RWC25按Meta实际WM_CLASS排除该应用后消失，用户确认。它是宿主策略的独立问题，不属于此Wine补丁 |

测试程序构建遇到既有format警告，仅对两个测试对象降级该类警告；未改断言、测试源码或生产编译选项。隔离测试全部停止并核对命名空间清理；真实客户端只做已授权的UI/桌面预览，没有游戏内存/反作弊探针。全程未开播。

## 排查与失败分支

1. 单独alpha开关、关闭GPU、关闭DirectComposition均没有修复实际黑底，最后一种还使预览变黑，均拒绝作为解决方案。
2. v1尝试GDI surface flush保留alpha，对GPU跨进程复制无效，已撤回；v2不包含该修改。
3. 自有样本初次TTL到期后读到空列表，不能当通过；延长TTL后重新采样。初次菜单淡入alpha170也保留，另取稳态alpha255控制值。
4. 两次直接启动conformance程序未捕获控制台输出，废弃；采用cmd重定向得到实际断言/失败记录。
5. RWC最初加入可读中文类名没有命中。现有窗口选择器返回的Meta类名实际上是UTF8字节按Latin1解码；使用其实际返回值后生效。没有全局关闭扩展。

## 启用、回退及限制

此补丁仍需要原有 `WINE_LAYERED_OVERLAY_ALPHA=1`，不是自动适用于全部程序的新默认。实机只把伴侣控制器指向独立v2 runner并启用该变量，保留旧runner及控制器备份；回退须在停止这一专用会话后切回旧控制器/runner再重开，不能热替换模块。RWC排除项单独回退，仅删除本任务新增的实际类名，保留其他应用条目。

整桌面摄像头桥已在此前通过本地游戏菜单录像，但直接WGC仍缺接口，完整安装、长时间游戏、精确音画同步与真实开播未验收；本轮结果不改变这些边界。

公开[里程碑](../../felix-proton/docs/WINE_TRANSPARENCY.md)、[通用接入评估](../../felix-proton/docs/WINE_TRANSPARENCY_INTEGRATION_ASSESSMENT.md)和[源码SHA256清单](../../felix-proton/docs/TRANSPARENCY_SOURCE_MANIFEST.json)提供本次同步范围；没有上传真实桌面、账号配置或厂商程序。
