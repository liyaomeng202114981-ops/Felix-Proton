# Felix-Proton 工作分类与文档目录

更新于2026-11-18。按工作领域回看和接续，保留原源码/文档路径。本次整理不安装运行器或更改使用配置。

## 按领域查找

| 类别 | 内容与记录入口 | 实现/验证入口 |
| --- | --- | --- |
| Proton / Wine底层修复 | [补丁报告总表](../../fixes/README.md)：网络0062/0063、UI0067/0068/0069/0070分别在所属领域继续维护，保留上游历史 | [Wine补丁](../../../patches/wine/) · [构建说明](../../README.md) |
| 网络与Steam/UU集成 | [实现逻辑](IMPLEMENTATION.md)：共享网络、原图标接入、CM连接保护；[诊断/回退](DIAGNOSTICS.md) | [native-ux](../src/native-ux/README.md) · [测试](TESTING.md) |
| UI兼容与桌面显示 | [UI工作总览与下一步](UI_COMPATIBILITY.md)：透明像素、外框、宿主效果和按应用适配 | [0067报告](../../fixes/0067-argb-other-process/README.md) · [自有样本](../../tests/argb_client_fixture/README.md) |
| UI窗口输入/移动/状态 | [此前问题链与通用解决方案](UI_WINDOW_COMPATIBILITY.md)：白带、最大化下拖及贴边拖出用户复测通过 | [0068输入](../../fixes/0068-composed-alpha-input/README.md) · [0069移动](../../fixes/0069-native-maximized-move/README.md) · [0070状态](../../fixes/0070-profiled-layered-csd/README.md) · [SHA清单](UI_WINDOW_SOURCE_MANIFEST.json) |
| 安装、打包与发行 | [从零流程](FROM_ZERO.md) · [实际安装说明](../packaging/fromzero/INSTALL.md) | [安装验收](SETUP_TEST_RESULTS.md) · [现有发行](https://github.com/liyaomeng202114981-ops/Felix-Proton/releases) |
| 工具与入口管理 | [Felix配对工具](../src/pairing-tool/README.md)：一次配对、原图标、配置持久化与恢复 | [工具测试](../src/pairing-tool/TEST_RESULTS.md) · [发行说明](../src/pairing-tool/RELEASE_NOTES.md) |
| Ubuntu 直播伴侣 | [直连开播与实测总览](STREAMING_COMPATIBILITY.md) | [画面与声音](streaming/AUDIO_VIDEO.md) · [原图标重开](streaming/STARTUP_RECOVERY.md) · [代理与 DNS](streaming/PROXY_DNS.md) |
| 维护、验证与来源 | [当前公开状态](CURRENT_STATE.md) · [工作日志](WORK_REPORT.md) · [源码目录](SOURCE_LAYOUT.md) | [验证汇总](TESTING.md) · [上游来源/许可](PROVENANCE.md) |

## 本次UI里程碑的材料位置

| 要看什么 | 入口 |
| --- | --- |
| 问题、根因与已解决范围 | [透明黑底/外框里程碑](WINE_TRANSPARENCY.md) |
| 精确修改及失败分支 | [0067源码报告](../../fixes/0067-argb-other-process/README.md) |
| 已验证/未验证项目 | [透明修复测试范围](TRANSPARENCY_TEST_RESULTS.md) |
| 后续通用接入建议 | [接入评估](WINE_TRANSPARENCY_INTEGRATION_ASSESSMENT.md) |
| 对应源码和合成结果校验 | [SHA256清单](TRANSPARENCY_SOURCE_MANIFEST.json) |

源码与结果基线为[3b454a57](https://github.com/liyaomeng202114981-ops/Felix-Proton/commit/3b454a573bc1b407d26783b408213660ada09973)。通用接入目前为评估，不能从“UI候选修复通过”推导出全局部署或新发行已完成。

## 后续每项工作怎么记录

每项在所属领域保留主要记录，跨领域用链接关联。记录应包含目的、状态、源码/版本、验证及失败、遗留事项/下一步、回退方式和GitHub提交。区分已验证实现、用户复测、静态评估、待实现及待验证；撤回或失败的候选保留原结论。当前状态和工作日志提供时间线，本目录提供分类入口。

原始桌面、账号/配置、厂商文件和本机日志不进公开目录。源码同步、二进制发行、安装和实际使用验收分别记录。
