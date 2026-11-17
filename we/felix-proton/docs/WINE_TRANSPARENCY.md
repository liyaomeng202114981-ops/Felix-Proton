# Wine外部黑底与透明框：修复里程碑

2026-11-17，Felix Li，with OpenAI Codex assistance。本次公开修复源码、通用自有样本和脱敏结果；没有发布新的运行器或改变现有安装。用户已分别复测确认直播伴侣13.2.5的黑色填充消失、随后残留的大透明框消失。

## 两层问题与解决办法

| 层次 | 已确认原因 | 已验证解决 |
| --- | --- | --- |
| Wine跨进程GPU绘图 | ARGB选择遗漏other-process客户端visual/colormap；离屏源DC仍用默认RGB格式，把透明像素补成alpha255 | [0067补丁](../../../patches/wine/0067-winex11-Preserve-opt-in-ARGB-formats-for-other-process-surfaces.patch)保留实际格式。真实1280×720辅助窗921600像素全alpha0，工具窗空白尾部透明，桌面预览可见 |
| GNOME/RWC附加效果 | 源像素透明后，RWC仍按整窗加圆角/阴影；可读中文WM_CLASS规则与Meta实际消费值不匹配 | 用扩展现有窗口选择器取得实际Meta类名，只修正目标应用排除项，保留此前规则；用户确认大透明框消失 |

本机的类名差异可表达为`"直播伴侣.exe".encode("utf8").decode("latin1")`，但不能把这个转换当成所有应用或Mutter版本的固定规则。可复用的方法是读取消费端的实际值，确认匹配确实生效，而非只看配置中是否出现了应用名称。

本次RWC处理是整应用类级排除，也取消RWC对该类主窗的效果；它没有修改应用像素、大小、输入区域或WM_CLASS，没有全局关闭扩展。通用helper-only接口仍需独立实现。

## 与已有工作的联系

此前迅游的可逆RWC A-B-A和helper-only试验已表明宿主可增加额外外沿；它保留应用原阴影及主体圆角。本次进一步把源ARGB丢失与宿主外框分别定位，并增加Meta实际类名匹配这一检查点。迅游的原始阴影、其他客户端的移动/灰帧/退出异常不因此自动算解决，也不应把其固定版本策略直接套给所有程序。

建议后续按当前prefix/runner/进程身份确认目标，区分主窗、辅助窗和弹窗，同时核对源RGBA与桌面合成画面。32bit格式不等于空白区域真的alpha0。使用自有透明区域、真正不透明黑色及普通不透明窗口做控制，分别检查绘图与宿主效果；候选独立构建、默认不改变其他应用，原设置可精确回退。

## 已保存成果与边界

- [完整技术报告](../../fixes/0067-argb-other-process/README.md)：根因、来源、固定SDK、失败尝试、回归和回退。
- [自有复现源码与前后输出](../../tests/argb_client_fixture/README.md)：不含厂商文件、账号或真实桌面；[测试范围](TRANSPARENCY_TEST_RESULTS.md)。
- [通用接入评估](WINE_TRANSPARENCY_INTEGRATION_ASSESSMENT.md)：Wine核心、按应用策略和可选宿主适配分开推进；尚未实施。
- [源码与结果SHA256](TRANSPARENCY_SOURCE_MANIFEST.json)：本次公开的精确材料清单。原始桌面/日志/账号/私有配置及测试二进制没有上传。

当前确认范围限于本机GNOME/XWayland、匹配的64位Unix驱动和既有alpha开关。没有原生Windows成对测试，也未覆盖原生Wine Wayland、独立i386 Unix驱动、所有工具包或多屏缩放。声音配置保持，本轮没有重新做声音/录制验收；实际开播和通用运行器安装尚未验收。此次源码同步不会升级既有Release。
