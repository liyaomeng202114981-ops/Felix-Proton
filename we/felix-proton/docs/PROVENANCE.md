# 来源、贡献与验证范围

Felix-Proton 是基于 WE-Proton 源码独立维护的项目。特别感谢 **SHORiN-KiWATA** 提供 WE-Proton 与 proton-wrapper，并感谢各上游项目的贡献者。新增工作由 **Felix Li 在 OpenAI Codex 协助下**完成。独立仓库保留已有 Git 历史、原作者、版权和逐组件许可证。

## 上游基础

Windows 加速器通过 Wine 使用 Linux 虚拟网卡的基础来自 **SHORiN-KiWATA 的 WE-Proton**。加速器与原生程序共享独立网络的会话管理来自同一作者的 **shorin-proton-wrapper**。命名空间与宿主网络之间的连接使用独立上游 **passt / pasta**。Felix-Proton 继承并调用这些能力。

| 来源 | 本项目使用的基础及归属 |
| --- | --- |
| [SHORiN-KiWATA/we-proton](https://github.com/SHORiN-KiWATA/we-proton) | 内置 Wintun 兼容实现，以及已有的接口、路由写入支持。历史开发基点为 [`4617d991e787603f5300c484f54b4bd61c776090`](https://github.com/SHORiN-KiWATA/we-proton/commit/4617d991e787603f5300c484f54b4bd61c776090)，对应 `we-proton-ge11-11-31`。 |
| [SHORiN-KiWATA/proton-wrapper](https://github.com/SHORiN-KiWATA/proton-wrapper) | 创建和复用独立网络命名空间、pasta 会话及 Wine／原生进程加入机制。受测原版脚本提交为 `d8ca9e73bf44d14eadfb29c95e17b57990e0b7f4`。本地启动入口通过 CLI 调用它。 |
| [passt / pasta](https://passt.top/) | 连接命名空间内的 TAP 与宿主 socket，由 Stefano Brivio、Red Hat 及项目贡献者开发。受测源码提交为 `6aa4f88bd9846411edff3ed70460475b538addca`，源码未修改。 |
| [GE-Proton](https://github.com/GloriousEggroll/proton-ge-custom)、[DW-Proton](https://dawn.wine/dawn-winery/dwproton) | WE-Proton 继承的构建及补丁基础，历史基底分别为 `GE-Proton11-11`、`dwproton-11.0-15`。 |
| [Valve Proton](https://github.com/ValveSoftware/Proton)、[Wine](https://www.winehq.org/)、[Valve Wine](https://github.com/ValveSoftware/wine) | Proton 运行器和 Windows API 实现。历史 Wine 子模块基点为 `c53678ab22a85f0fad3588dd34f0452a463bd015`。 |
| [Steam Linux Runtime / pressure-vessel](https://gitlab.steamos.cloud/steamrt/steam-runtime-tools) | Proton 运行所依赖的容器与兼容运行环境。 |

WE-Proton 的相关既有补丁包括 `0015` 网络接口与路由写入、`0016` 内置 Wintun、`0017` socket 接口选择、`0048` 适配器描述和 `0053` 旧式路由 API。Wintun API 的来源还应归于 [WireGuard 的 Wintun 项目](https://www.wintun.net/)，Linux TUN 与网络命名空间能力归于 Linux 内核及其贡献者。不能将 API 定义、内核功能、pasta 或 WE-Proton 的实现归为 Felix 的原创。

受测 wrapper 文件 SHA256 为 `19a5ed00b0571d48bb41c7e38e6f5a254db96e06b6b6370f2680caab265d997c`，与上述上游版本一致。受测 pasta 本地构建产物 SHA256 为 `1dd758b40ab9a6ba4fdd5fc6792c11bb180e87fdeb1b56eab6babe4d4a4b3ddd`。这些标识用于追溯历史验证，不表示任意更新版本已通过相同测试。

## Felix 的新增工作

| 工作 | 内容与边界 | 是否属于现有 PR #1 |
| --- | --- | --- |
| Wine 补丁 `0062` | 校验接口名称与当前索引，过滤已删除或被替换的缓存项，修复切换加速后仍返回旧接口的问题。原始开发提交为 `0784ca7162a8532a8587b9c3dcf38668379eb3ce`。 | 是 |
| Wine 补丁 `0063` | 在一次内部 IPv4／IPv6 路由枚举内复用成功的接口转换，消除 `0062` 重复检查带来的性能回退。下次枚举重新验证，没有跨调用 TTL 缓存。原始开发提交为 `28db1f7cd049a6f6e4be9fb5f8ce275868b7a4bb`。 | 是 |
| Steam 共享网络入口 | 让原生 Steam 进入加速器的已有网络会话，核对已运行实例的网络归属，保留各 Steam 游戏自己的 Wine prefix。 | 基础入口在 PR 内，后续本地集成另行维护 |
| 桌面兼容 `0061` | 恢复普通 Windows 程序的窗口身份与宿主装饰，并配合桌面入口辅助组件。原始 Wine 开发提交为 `6e1fb3f92cd8da1d8dfbdeb0a37afa6dd39ac4f9`。部分历史受测运行器含此补丁。 | 否 |
| 原有图标与启动接入 | 在原 UU／Steam 桌面入口、Dock 和 URI 启动路径上接入共享网络逻辑，减少用户记忆额外入口的需要。保留已有登录和前缀，不将程序商标或图标归为自有作品。 | 否 |
| 自动诊断 | 验证 keeper 身份与网络归属，观察设备、路由、计数器及有限进程元数据；提供有边界的状态与未知原因。诊断结果不能单独证明所有游戏流量或游戏体验已被加速。 | 否 |
| Python Steam CM 连接保护 | 在已验证的私有命名空间中，为已确认的 Steam 控制连接精确 IPv4 TCP 目标 IP 和端口保留 pasta 路径，减少切换 UU 路由导致的 Steam 断线。使用独立路由表、归属记录和可回退规则，不进行全部 TCP 443 或整用户分流。 | 否，属于 2026-11-05 的后续本地修复 |

`0062` 和 `0063` 应配套使用。前者单独使用曾使 3000 条路由的合成批量操作出现约八倍回退，后者将性能恢复至接近原有水平。它们没有消除旧 API 逐条操作及全表扫描的全部开销，也不能解释或修复客户端所有连接等待。

## PR 的准确状态

上游提案为 [SHORiN-KiWATA/we-proton PR #1](https://github.com/SHORiN-KiWATA/we-proton/pull/1)。2026-11-05 已核对的状态为 **open，merged = false**，来源分支为 `proposed-uu-network-fixes`，head 为 `159e2baf1efc5d148ee44ecdc5f0b3489089cb3d`。

该 PR 提交了网络两项修复、基础启动入口、测试与说明。上游尚未合并这些修改。本项目后续加入的桌面体验、自动诊断及 Python CM 保护不自动成为该 PR 的一部分，也不表示 WE-Proton、Valve、Wine 或网易已认可或提供支持。

## 已验证结果与限制

本地用户已完成实际切换加速的复测，并确认本轮 Steam 切换断线问题得到解决。这是当前机器、当前安装和受测切换流程的确认，不能推导为所有节点、游戏、网络或未来运行器版本都兼容。

用户随后确认 CM 目录查询修复与就绪通知所在的更新通过本机实测。隔离测试及本机反馈分别列于 [工作报告](WORK_REPORT.md)。

历史隔离验证覆盖接口创建、删除、同名重建、重命名，以及 IPv4／IPv6 路由枚举。`0063` 候选的旧回归共 212 项通过，新路由语义四组各 194 项通过。官方 NSI 测试 1453 项无失败；受控 IP Helper 测试两边均有相同的 45 项既有失败，并跳过两个已知挂起的 echo 子测试，不能写成官方测试全部通过。PE32 测试使用 WoW64，没有声称完成独立旧式 i386 Unix 运行验证或原生 Windows 对照。

Python CM 策略另外经过独立临时网络命名空间测试，覆盖精确 TCP 目标旁路、同 IP 其他 TCP 端口及 UDP 保持原路由、UU 路由移除、规则冲突、失败恢复和回退。实际部署后的用户反馈与隔离测试分别记录，互不替代。

最近一次退出游戏后的约 25% CPU 占用已定位为 Steam 的 `fossilize_replay` 后台着色器处理，日志和工作进程负载与之对应。内存当时仍充足。这项现象独立于本次加速切换修复，本项目没有因此更改 Steam 着色器设置，也不把它列为已修复的网络问题。处理用途可查 [Fossilize 官方说明](https://github.com/ValveSoftware/Fossilize#fossilize-replay) 和 [Valve 维护者解释](https://github.com/ValveSoftware/Proton/issues/7176)。

## 新目录与历史材料

| 位置 | 用途 |
| --- | --- |
| `src/native-ux/` | 本地安装、调度及原有入口接入代码，并归集后续连接保护集成。 |
| `src/live-watch/` | 有限元数据诊断与状态采样。 |
| 仓库根目录 | 保留 WE-Proton 的 Git 历史、Wine 补丁、测试和来源。历史本地 test.1 打包源码 HEAD 为 `df81380b6e2b582fe0fb0e37dca634add47977e9`；此公开分支并非该运行器的全新构建。 |
| `docs/TESTING.md` | 可公开的脱敏验证摘要；私人原始日志和配置保留本机，不随源码上传。 |

这些路径均以 `we/felix-proton/` 为起点。历史运行器、PR 源码和当前本地集成不是完全相同的产物，发布说明必须说明实际包含哪些补丁和组件。曾受测的含 `0061` 本地运行器不能被描述为不含该补丁的 PR 源码全新构建结果。

## 许可证与署名

| 范围 | 适用许可 |
| --- | --- |
| Proton 顶层及新增 Python／启动集成 | 保留随源码提供的 `LICENSE`、`LICENSE.proton` 及文件声明。当前新增集成使用 `BSD-3-Clause`，另有声明的文件除外。 |
| Wine 源码修改，包括 `0061`、`0062`、`0063` | `LGPL-2.1-or-later`，保留原文件作者、版权与 Wine 的许可文本。 |
| `ndis_interface_lifecycle_probe.c`、`route_perf_probe.c` 等测试 | 按逐文件许可，其中上述两个文件明确为 `LGPL-2.1-or-later`，不能因放在 `we/` 下而改为 BSD。 |
| shorin-proton-wrapper | 受测版本的 `nfpm.yaml` 声明 MIT，核对时根目录没有独立 `LICENSE`。保留这一来源事实，不用 Felix 的许可证替换上游声明。 |
| passt / pasta | 主要为 `GPL-2.0-or-later`，其余文件遵循自身声明；上游还包含 BSD 许可文件。 |
| 其他依赖、客户端与图标 | 保留各自版权和许可，不作统一重新许可。 |

新增实现、排查、测试与文档署名为 **Felix Li，with OpenAI Codex assistance**。已有 AI 协作的 `Co-Authored-By` 与上游提交作者信息一并保留。目录迁移和改名不转移其他项目的代码归属。

公开源码和归档不得包含用户原始日志、账号或令牌、既有 Wine prefix、游戏内容、个人绝对路径或私有网络端点。发布时保留可复现的通用测试、脱敏结果摘要、对应源码和许可证。网易 UU、Steam 及其商标属于各自权利人，本项目没有提供这些客户端的再许可或额外服务权益。
