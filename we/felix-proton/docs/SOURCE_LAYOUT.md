# 源码范围与组件关系

下列路径以 `we/felix-proton/` 为起点。这里是本机工作区经过审核的文件快照，没有引入私人工作区的 Git 历史。

| 路径 | 用途 |
| --- | --- |
| `src/native-ux/` | 当前普通图标集成、安装/恢复、Steam 窗口唤出、CM 端点发现和精确策略及测试 |
| `src/live-watch/` | 有时限的被动观察、Steam 事件分类与游戏路由判断及测试 |
| `src/test-runtime-felix/` | 历史 test.1 附加启动与诊断组件；采集器测试从中加载网络判断模块 |
| `src/network-launchers/` | 便携显式共享网络入口的工作区快照；历史公开版本仍位于仓库 `we/integration/uu-network/` |
| `src/test-integration/`、`src/test-diagnostics/` | 历史测试集成与诊断组件的独立来源快照 |
| `packaging/test.1/` | 参数化历史运行器再打包脚本、版本元数据与构建边界 |
| `packaging/portable-onboard/` | 早期便携引导源码，非当前普通图标主入口 |
| `scripts/pack_native_preview.py` | 本地预览打包及固定运行器校验，需要另行准备历史二进制 |

Wine 0062/0063 补丁及其报告继续放在仓库根的 `patches/wine/`、`we/fixes/` 与 `we/tests/`，未在此复制另一套。0061 桌面模块及 test.1 的历史打包来源在元数据和 [来源说明](PROVENANCE.md) 中列明；公开网络分支并非含全部历史桌面模块的运行器全新构建。

测试文件中的地址、账号式字符串和 token 字样用于合成输入，测试中的外部请求被替身替代；这些文件不包含实际端点发现结果、账号配置或用户日志。生产端点发现代码会按说明请求 Valve CM 目录，运行时工具仍需遵守各自使用说明。

本次上传不包含运行器、已有 Wine 前缀、个人日志、真实配置、私有证据目录和客户端安装包。源码公开不等同于异机安装或全部客户端兼容验收。
