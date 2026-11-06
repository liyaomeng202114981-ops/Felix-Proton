# Felix-Proton：普通图标集成与 Steam 连接保护

这是由 Felix Li 在 OpenAI Codex 协助下独立维护的 Felix-Proton 启动集成。感谢 SHORiN-KiWATA 为 Wine 网络适配和共享网络会话提供的基础，也感谢 passt / pasta 的贡献者。仓库保留各组件的作者、版权、许可与提交历史。[WE-Proton](https://github.com/SHORiN-KiWATA/we-proton) · [proton-wrapper](https://github.com/SHORiN-KiWATA/proton-wrapper) · [passt / pasta](https://passt.top/)

本轮公开的是最新 Python 启动层、安装与回退、诊断工具、配套测试及工作说明。Wine 网络补丁 0062/0063 仍位于本仓库原有的 `patches/wine/` 和 `we/fixes/` 中；这里没有重新编译或发布 Proton 二进制。

当前以开发中的具体流程和实现说明为主，暂不构建发行版、发布固定运行器或创建 Release。仍有问题需排查和跨机验证，详见下面的完整流程与当前状态。

- [从零配置完整流程说明（开发记录）：材料、步骤、手动分解、验证与回退](docs/FROM_ZERO.md)
- [实现逻辑与代码导航：无感启动、网卡切换和 CM 保护](docs/IMPLEMENTATION.md)
- [本轮工作与验证结果](docs/WORK_REPORT.md)
- [当前结果与未解决事项](docs/CURRENT_STATE.md)
- [普通 Steam / UU 图标的使用说明](src/native-ux/README.md)
- [测试与证据边界](docs/TESTING.md)
- [只读诊断与回退](docs/DIAGNOSTICS.md)
- [上游来源、贡献与许可](docs/PROVENANCE.md)
- [源码与历史组件说明](docs/SOURCE_LAYOUT.md)

## 日常使用

本机部署后照常使用原来的 Steam 和网易 UU 图标。启动层通过上游 wrapper 自动安排共享网络；由该 Steam 启动的游戏通常继承相同网络，各自的 Proton 版本、前缀与启动参数仍由 Steam 管理。在 UU 中选择游戏、区服、路由模式和节点，决定具体加速目标。

新增 CM 保护只为已确认的精确 IPv4/TCP Steam 登录及在线控制端点保留加速前的 pasta 出口。游戏路由继续由 UU 管理。用户已确认本机切换加速时原有 Steam 掉线问题得到解决；这不保证游戏自身连接切换不中断。

用户已确认目录查询修复与就绪提示所在的 CM 更新通过本机实测。隔离测试和本机复测分别记录。[工作报告](docs/WORK_REPORT.md)

## 源码与运行器的区别

仓库克隆内容不包含 `felix-proton-uu-test-0.1.0-test.1.tar.zst`、客户端安装包或现成 Wine 前缀。`src/native-ux/enable.py` 可以复用本机已验证的 test.1 配置；全新安装和 `scripts/pack_native_preview.py` 需要另行准备固定 SHA-256 的历史运行器，不能仅凭本源码快照完成。构建、打包和安装应分开进行，具体依赖见使用说明及 `packaging/test.1/BUILD.md`。

当前验证主要来自一台 Linux 机器，尚无异机端到端验收。没有以代码测试或路由命中代替所有游戏、节点的加速效果验证。加速启动等待约 10～30 秒、UU 固定窗口尺寸的状态见当前结果。

## 署名与许可

共享网络会话、Wintun 基础、pasta 与其他上游组件保留各自作者、历史和许可。新增集成代码遵循随文件提供的 BSD-3-Clause 声明；Wine 修改及相关探针按 LGPL-2.1-or-later 等逐文件许可处理。保留 `LICENSE`、`LICENSE.proton` 和原有版权信息。
