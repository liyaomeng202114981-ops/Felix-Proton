# 用原来的 Steam 和网易 UU 图标

首次从零配置及手动步骤见 [完整部署指南](../../docs/FROM_ZERO.md)，包含固定运行器前提、共享网络、CM 保护、图标接入与回退。

安装后，照常打开 Steam 或网易 UU。先开 Steam 也可以。需要加速时，在 UU 里选择游戏、区服和支持路由模式的节点，点击加速。日常不需要使用组合启动器或设置单个游戏的启动参数。

Steam 已运行时再点普通 Steam 图标，会尝试把已有的 Steam 主窗口或登录窗口带到前台。此功能适用于可识别的 X11/XWayland 窗口，需要 wmctrl 与 xprop。没有可验证的窗口时，会通过原来的 Steam 网络入口发送“打开游戏库”命令。登录操作在 Steam 自己的窗口完成。

## 原理与范围

桌面入口继续使用正常的 `steam.desktop` 和 `uu-accelerator.desktop`。被启动的应用先通过原作者的 wrapper 进入同一前缀的 Linux 网络命名空间。先启动的一方创建会话，后启动的一方加入。未加速时，Steam 经该网络的 pasta 默认出口联网。点加速时，UU 在这个网络里建虚拟网卡并写入所选目标的路由；正常停止后由 UU 移除。已建立的游戏连接有时要重新连接才能体现新的路由。

通过普通图标启动的原生 Steam、现有右键菜单以及由同一个 desktop ID 处理的 steam:// 链接使用这套配置。大部分由该 Steam 启动的游戏继承这个网络，可以保留各自的 Proton 版本。其他启动器或写死了系统 Steam 可执行路径的脚本，在 Steam 尚未运行时可能另起一个网络外的客户端。如果已经有这样的实例，请正常退出一次，再点普通 Steam 图标。

## 减少切换加速时的 Steam 断线

本机日志显示，停止 UU 加速时，Steam 的登录控制连接可能因出口和源地址改变而断开，随后重连需要约 22～34 秒。控制连接保护会在启动应用前取得 Valve 官方 CM 目录，并结合 Steam 本地日志中的 CM 候选地址，在专用网络内安装准确到 IPv4 地址和 TCP 端口的策略规则。它让这些控制连接持续使用加速前的 pasta 出口，游戏连接继续使用 UU 的路由。不修改宿主机路由，也不代理整个 Steam 或全部 443 端口。

普通图标会自动启动保护，无需为每款游戏填写参数。首次就绪时会显示“连接保护已就绪”，每个守护会话提示一次。保护暂未就绪时应用仍可启动，后台首次恢复后会补发就绪通知。目录查询可使用 GNOME 手动配置的本机代理，细节见 [实现逻辑](../../docs/IMPLEMENTATION.md)。规则数量和错误码保存在 `$XDG_RUNTIME_DIR/felix-steam-cm/`；有容量限制的事件日志保存在 `$XDG_STATE_HOME/felix-steam-cm/`，默认不记录账号、聊天内容或原始网络日志。取得原出口要求 UU 尚未创建加速网卡；首次安装时请停止加速，再打开普通 Steam 或 UU 图标。

此保护只覆盖已发现的 IPv4 CM TCP 端点。新服务器尚未发现、IPv6、下载 CDN、游戏自己的登录连接和互联网本身故障仍可能导致断线。同一地址和同一端口若被其他应用使用，也会匹配规则。已经通过 UU 建立的连接会先保留原路径，等断开后再保护，避免中途强行换源地址。它不保证游戏连接在停止加速时不断线，也不会强制重启 Steam 来恢复会话。

临时回退：先停止 UU 加速，再执行 `python3 ~/.local/share/felix-native-ux/v1/cm_guard.py stop`。停止会移除该守护程序登记的规则；下一次点普通入口会重新启用。需要持续停用时，可在启动器环境中设置 `FELIX_STEAM_CM_GUARD=0`。查询状态用同一路径加 `status` 参数。恢复原桌面入口仍使用下面的 `enable.py restore`。

## 首次启用

当前 GitHub 发布仅包含源码，不包含固定 test.1 运行器归档。下述启用流程适用于已有已验证 test.1 配置，或另行备齐受校验历史运行器的本地预览包；直接 clone 本仓库不能完成全新安装。

本地预览使用 x86-64 Linux 的原生 Steam、Python 3.10+、zstd、[shorin-proton-wrapper](https://github.com/SHORiN-KiWATA/proton-wrapper) 和符合此试用版要求的 [pasta](https://passt.top/passt/about/)。系统需允许非特权用户命名空间并可用 /dev/net/tun。适配发行版的安全策略和 Steam Runtime 首次下载仍由系统及 wrapper 负责。本版尚未在其他实际机器验收。

在解压目录运行一次：
```sh
python3 enable.py
```

如果已经安装 Felix test.1，会复用其已验证的配置、运行器和 UU 前缀，保留该前缀中的账号状态。新安装使用包内的固定版本运行器，会先提示选择从[网易 UU 官网](https://uu.163.com/)下载的 Windows 安装程序。完成首次 UU 安装后，才改动桌面关联。没有图形文件选择器时，可以指定 `--uu-installer "/路径/UU安装包.exe"`。正常登录后即可在 UU 选游戏。

安装器备份并修改用户级应用条目，保留 Steam 的桌面 ID、图标、名称及已识别动作。没有网易 UU 应用条目的新环境会生成普通的「网易 UU 加速器」图标。旧的专用试用图标仅在能确认归属时折叠。它不修改 Steam 程序、宿主机路由或系统范围的 MIME 配置。

本地备份位于 `$XDG_STATE_HOME/felix-native-ux/`（默认 `~/.local/state/felix-native-ux/`）。在解压目录执行以下命令可恢复备份的入口。若文件已被其他工具更改，安装器会报告冲突并保留现场：
```sh
python3 enable.py restore
```

## 署名及本轮验证

SHORiN-KiWATA 的 [WE-Proton](https://github.com/SHORiN-KiWATA/we-proton) 实现 Wine 内置 Wintun 和 UU 所需的路由接口，配套 wrapper 管理共享网络及原生 Steam 的加入。Felix Li 在 OpenAI Codex 协助下完成失效网卡修复 0062、路由枚举修复 0063、启动保护和诊断，将这些能力接到日常图标，并增加本节的 CM 控制连接保护。CM 保护是 Python 启动层的附加功能，不属于原作者实现的 Wine Wintun 补丁。[此前补丁与验证](https://github.com/SHORiN-KiWATA/we-proton/pull/1)

本轮检查覆盖隔离的启动顺序、URI 和参数传递、跨网络保护、安装与恢复，以及本机桌面解析和已有客户端的网络状态。CM 策略另在真实隔离网络命名空间中验证：模拟 UU 路由接管与网卡撤除后，CM TCP 仍选原出口，同地址其他 TCP 端口及 UDP 不受保护规则影响；还覆盖规则回收、外来规则冲突、写入失败恢复和端点缓存失效。用户随后复测并明确反馈已解决切换时 Steam 掉线；复测未覆盖整夜监测，未测得新的逐次断线时长。本目录公开启动层源码及测试；固定 test.1 运行器仍是本机预览，本次没有发布二进制或完成异机验收。对应来源与发布范围见 [项目说明](../../README.md)。
