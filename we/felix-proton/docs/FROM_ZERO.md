# 从零配置完整流程说明：材料、操作、实现与回退（开发记录）

更新于 **2026-11-06**。维护者：**Felix Li，with OpenAI Codex assistance**。

本文把安装原生 Steam、Windows UU、共享网络、Wine 修复、Steam CM 连接保护、普通图标接入和诊断串成一条完整流程。命令是供使用者按步骤操作的说明，本次文档整理没有在用户机器上执行安装或切换网络。

**当前定位为开发中的实现和手动配置记录，暂不构建发行版、发布固定运行器或创建 GitHub Release。这里的“完整”表示说明覆盖当前各层功能，不表示全部问题已解决，也不表示新机器仅下载仓库就能直接安装。**

## 手动操作顺序概览

| 顺序 | 操作 | 说明位置 |
| --- | --- | --- |
| 1 | 安装原生 Linux Steam，运行一次初始化，再正常退出 | 第 1 节 |
| 2 | 准备 Windows UU 安装包、wrapper、合适的 pasta、系统工具与权限 | 第 0～1 节 |
| 3 | 取得当前集成源码，核对固定运行器及依赖；缺少材料时先明确缺口 | 第 2 节 |
| 4 | 校验并安装运行器，生成同一版本绑定的配置、UU 前缀与独立网络设置 | 第 3～5 节 |
| 5 | 在该前缀中先完成 Windows 初始化和 UU 安装，确认默认客户端文件存在 | 第 3、5 节 |
| 6 | 安装 Python 启动层、写活跃配置、备份并接入普通 Steam/UU 图标 | 第 3～5 节 |
| 7 | UU 尚未加速时准备共享网络及 CM 精确保护，分别核对就绪状态 | 第 6、9 节 |
| 8 | 让 Steam、UU 进入同一网络；在 UU 选游戏/区服/路由模式/节点并开始加速，再启动游戏 | 第 7 节 |
| 9 | 切换目标时正常结束当前游戏、UU 停止旧目标后重新选择；分别观察 Steam 在线和实际连接 | 第 7、9 节 |
| 10 | 需要回退时按停止加速、停保护、恢复入口、正常退出和重开顺序操作 | 第 10 节 |

第 3 节给受支持的完整安装命令，第 5 节把它分开供手动理解和操作；两条路径选一条。后续章节说明每一步生成的文件、代码职责、验收和限制。

## 已解决、仍待处理和未验收

| 分类 | 当前结论 |
| --- | --- |
| 已有修复及本机结果 | 0062/0063 修复接口身份与新增查询回退；普通图标接入已实现；用户已确认本机原有 Steam 切换掉线问题解决 |
| 已移出项目排查范围 | 用户排查将先前内核崩溃归因于 Snap 版 Office，见 [当前状态](CURRENT_STATE.md) |
| 已接受或暂缓 | 加速启动约 10～30 秒尚未全面归因，用户可接受；UU 自由缩放暂缓 |
| 尚未覆盖或验收 | 异机和全部游戏/节点兼容、IPv6/新 CM 端点/游戏自身连接稳定性；当前没有对应运行器的公开下载资产 |
| 已归因并按要求保留 | Steam Fossilize 的历史 CPU 占用，不调整其设置 |

用户的单项验收、隔离测试、路由命中和实际游戏效果分别记录；继续开发时沿用这些边界。

## 0. 先明确“当前完整功能”和材料条件

目标是：使用原来的 Steam / UU 图标，自动准备同一网络；在 UU 中选择游戏、区服、路由模式和节点；Steam 启动的普通游戏通常继承该网络；切换加速时，已保护的 Steam CM 登录/在线连接保持原出口；保留已有窗口唤出、诊断和桌面入口回退。

**当前全功能安装器锁定历史 `0.1.0-test.1` 运行器。其固定归档目前仅有本地预览，尚未在本 GitHub 项目公开分发。下面的完整安装流程以已经取得该归档为前提；只 clone 公开源码不足以完成全新安装。**

| 必需材料 | 用途及当前状态 |
| --- | --- |
| 原生 Linux Steam | 提供 Steam 客户端和游戏管理；安装后先运行一次初始化。当前安装器不支持把 Flatpak/Snap 当作等价替代 |
| 官方 Windows UU 安装程序 `.exe` | 安装到专用 Wine 前缀；由用户从 UU 官方渠道取得，仓库不附客户端和账号 |
| shorin-proton-wrapper | 创建和复用按前缀标识的独立网络，启动 Windows UU 与原生 Steam |
| 合适的 pasta / passt | 独立网络的基础出口；需要当前版本检查要求的功能 |
| 固定 test.1 运行器归档 | 含历史桌面模块及 0062/0063 网络模块；本机已有，GitHub 未发布二进制 |
| 本仓库 `we/felix-proton/` | 最新 Python 启动层、CM 保护、诊断、测试与本文；已经公开 |

固定文件名与 SHA-256：

```text
felix-proton-uu-test-0.1.0-test.1.tar.zst
320d1a9fce1bd4a885c6cc88c35db50411234c0e5f477e167e15460d09362fea
```

任意 WE-Proton、把文件夹改名、重新压缩的归档都不能当作这个文件。安装器还校验 `felix-build.json`、`proton` 和两架构 `nsiproxy.so` 的指纹。源码构建与发布材料缺口见第 11 节。

## 1. 先安装 Steam，再准备依赖

从 [Steam 官方页面](https://store.steampowered.com/about/) 或发行版支持的原生渠道安装 Linux Steam，运行一次完成初始化，然后从 Steam 菜单正常退出。关闭窗口不一定退出后台客户端。首次 UU 初始化完成前，不要先让 Steam 加入新建的 UU 网络。

从 [网易 UU 官网](https://uu.163.com/) 获取 Windows 安装包，保留在本机。此处的 UU 是将经 WE-Proton 运行的 Windows 程序。

安装 wrapper 按 [上游安装说明](https://github.com/SHORiN-KiWATA/proton-wrapper#安装) 进行。受测 wrapper 提交为 `d8ca9e73bf44d14eadfb29c95e17b57990e0b7f4`；本机受测 pasta 源码提交为 `6aa4f88bd9846411edff3ed70460475b538addca`。其他版本需要重新核对功能和实际行为。

| 层面 | 要求 |
| --- | --- |
| 系统 | x86-64 Linux、Python 3.10+、Bash；允许所需的非特权 user/net namespace，当前用户可访问 `/dev/net/tun` |
| 基础工具 | `zstd`、`flock`、`nsenter`、`unshare`、iproute2；安装运行器至少需要 2 GiB 临时可用空间，Steam Runtime 另需下载/空间 |
| wrapper | 支持 `--prefix`、`--runner`、`--netns` 和原生 Linux 程序加入网络；保留其正常 Steam Linux Runtime 配置 |
| pasta | 当前安装器检查 `--config-net`、`--ns-mac-addr`、`--no-pidns`；不能仅凭安装了名叫 passt 的包判断兼容 |
| CM 策略 | 当前实现调用 `/usr/bin/nsenter` 和 `/usr/sbin/ip`，需要 IPv4 TCP 目的端口策略规则功能 |
| 已有窗口唤出 | X11/XWayland、可用的 `DISPLAY`、`wmctrl` 和 `xprop`；缺少时回退到 Steam URI 请求 |
| 桌面通知 | `notify-send`；`update-desktop-database` 用于可选的桌面数据库刷新 |
| 首次选安装包 | 不显式传 `--uu-installer` 时可用 `zenity`；本文显式给路径，不依赖选择器 |
| 语言 | 当前配置默认 `zh_CN.UTF-8`，系统应提供该 locale |

wrapper 在需要时准备对应 Steam Linux Runtime；不把运行器的 `proton` 直接当宿主机 Wine 命令运行。相关行为见上游说明。pasta 的网络连接职责见 [官方说明](https://passt.top/passt/about/)。权限或系统策略不满足时先记录具体错误，不为安装而盲目关闭系统安全限制。

## 2. 取得当前集成源码，检查材料

在准备放源码的目录执行一次：

```sh
git clone --branch uu-network-integration --single-branch \
  https://github.com/liyaomeng202114981-ops/we-proton.git Felix-Proton-source
cd Felix-Proton-source/we/felix-proton/src/native-ux
```

下面命令均从这个 `src/native-ux` 目录执行，路径按实际下载位置修改。不要修改 `HOME`：

```sh
fp_runtime_archive="$HOME/Downloads/felix-proton-uu-test-0.1.0-test.1.tar.zst"
fp_uu_installer="$HOME/Downloads/UU安装包.exe"

printf '%s  %s\n' \
  '320d1a9fce1bd4a885c6cc88c35db50411234c0e5f477e167e15460d09362fea' \
  "$fp_runtime_archive" | sha256sum -c -

python3 -B bootstrap.py --check --json --uu-installer "$fp_uu_installer"
test -x /usr/bin/nsenter && test -x /usr/sbin/ip
```

`bootstrap.py --check` 只做依赖和安装包检查，不初始化前缀或网络。它通过并不代表 CM 已启动，也不涵盖所有窗口工具或系统策略的实际可用性。后面的运行验收仍必须完成。

## 3. 从空白状态完成全功能安装

在首次安装的空闲环境中执行：

```sh
python3 -B enable.py \
  --archive "$fp_runtime_archive" \
  --uu-installer "$fp_uu_installer"
```

按出现的官方 UU 安装界面完成安装；Steam 和 UU 的登录始终在客户端自己的界面进行。安装完成后再按第 6 节启用首次网络会话，暂时不要先开始加速。

这个命令实际依次完成下列工作，因此它覆盖了基础共享网络之外的完整功能：

1. 检查依赖、归档哈希、路径和归属；安装固定运行器到原生 Steam 的 `compatibilitytools.d`。
2. 创建本版本的专用配置和前缀，设置 `netns=1` 及私有权限和归属标记。
3. 通过该运行器及 wrapper 初始化 Windows 环境、运行 UU 安装程序；首次 Windows 初始化先于原生 Steam 加入网络。
4. 确认 Windows 注册表及 UU 启动文件存在，才继续接入普通图标。
5. 安装 9 个 Python 启动层文件，写入活跃配置指针；其中包含 CM 保护和已有 Steam 窗口唤出逻辑。
6. 备份并改写用户级普通桌面入口，保留图标、desktop ID、Steam URI/右键动作及参数处理，按归属识别旧测试入口。

已有 UU 条目会保留原图标；全新机器尚无该条目时，安装器创建普通「网易 UU 加速器」入口，目前备用图标为 `network-vpn`，不保证自动取得与本机现有条目相同的 UU 商标图标。这不新增组合入口。

安装器保留不属于本版本的目录和用户修改。任意手工建的 `UU-Manual` 前缀不能随后被它当作当前 test.1 前缀直接接管；不要通过手写假归属标记或删除哈希校验来绕过检查。

## 4. 安装后究竟多了哪些文件

以下为默认 XDG 路径；如果配置了 XDG 环境变量，以程序实际解析结果为准。

| 位置 | 内容和用途 |
| --- | --- |
| Steam 根目录下 `compatibilitytools.d/felix-proton-uu-test-0.1.0-test.1/` | 固定运行器和历史 `felix/launchers`、观察组件 |
| `~/Games/Felix-UU-0.1.0-test.1/` | UU 专用前缀；Windows 环境在其中的 `pfx/` |
| `~/.config/felix-uu-test/0.1.0-test.1/config.json` | 同一前缀、运行器、wrapper、原生 Steam、pasta 目录和 UU 程序路径的绑定 |
| `~/.config/felix-native-ux/active.json` | 指向上述配置，格式为 `{"config":"配置文件的绝对路径"}` |
| `~/.local/share/felix-native-ux/v1/` | `policy.py`、`endpoints.py`、`cm_guard.py`、`steam_window.py`、`desktop.py`、`setup_config.py`、`bootstrap.py`、`routes.py`、`enable.py` |
| `~/.local/share/applications/steam.desktop`、`uu-accelerator.desktop` | 原图标的用户级启动入口 |
| `~/.local/state/felix-native-ux/desktop-backup-v1/` | 桌面入口恢复所需的备份与状态 |

配置核心字段为 `prefix`、`runner`、`wrapper`、`steam_real`，另有 `pasta_bin_dir`、`uu_executable`、`uu_locale` 等。当前 test.1 配置要求真实绝对路径；示例配置中的 `~` 不能不经转换就照抄成这份私有配置。`steam_real` 指向真正的原生 Steam 入口，不能回指我们的启动层造成递归。

## 5. 如果要把安装过程分开手动操作

第 3 节是受支持的完整 CLI。以下用于理解和审阅它的具体顺序：使用相同模块分步操作当前固定版本，不是给任意运行器/任意前缀的通用安装 API。第 3 节与本节选一条安装路径，不必都做。

首先保持第 2 节的工作目录和变量，并把本轮路径传给准备模块：

```sh
export FELIX_REPRO_ARCHIVE="$fp_runtime_archive"
export FELIX_REPRO_UU_INSTALLER="$fp_uu_installer"
python3 -B - <<'PY'
import os
from pathlib import Path
import setup_config
config = setup_config.ensure_config(
    Path(os.environ['FELIX_REPRO_ARCHIVE']),
    uu_installer=Path(os.environ['FELIX_REPRO_UU_INSTALLER']))
print(config)
PY
```

这一步使用安装器内部函数校验/安装固定运行器，生成受检查的版本配置、私有前缀、归属标记和 `netns=1`，尚未安装 UU、改图标或启动 CM。不能把输出写成个人资料上传到仓库。

用生成的同一配置运行 UU 安装程序：

```sh
fp_config_base="${XDG_CONFIG_HOME:-$HOME/.config}"
export FELIX_REPRO_CONFIG="$fp_config_base/felix-uu-test/0.1.0-test.1/config.json"
python3 -B - <<'PY'
import os
import sys
from pathlib import Path
import routes
ctx = routes.load(Path(os.environ['FELIX_REPRO_CONFIG']))
argv, env = routes.command(ctx, 'setup', [os.environ['FELIX_REPRO_UU_INSTALLER']])
os.execve(sys.executable, argv, env)
PY
```

该模块调用保留 UU 专用环境和诊断执行层，经 wrapper 为此前缀完成 Windows 初始化并启动安装器；不在此之前创建原生 Steam 的持久会话。安装结束后检查这两个文件存在，实际客户端路径以配置为准；此固定版本默认使用以下位置：

```sh
test -f "$HOME/Games/Felix-UU-0.1.0-test.1/pfx/system.reg"
test -f "$HOME/Games/Felix-UU-0.1.0-test.1/pfx/drive_c/Program Files (x86)/Netease/UU/uu_launcher.exe"
```

安装程序若启动 UU，先完成安装并保持未加速，按需要正常退出安装器/客户端，再执行：

```sh
python3 -B enable.py
```

最后这一步复用已经校验的本版配置与 UU 安装，完成 9 个辅助模块、活跃指针、原图标备份/改写及桌面刷新。避免手工复制一半文件或漏掉 `endpoints.py`、`policy.py` 而误以为 CM 保护已经装好。安装完成仍需下一节的首次启用。

## 6. CM 保护必须在 UU 加速之前准备

`enable.py` 完成的是安装，**首次点普通 Steam/UU 图标时才会自动调用 `cm_guard.ensure()`**。默认会先创建/确认网络，记录原出口，发现端点并准备规则，再启动所选应用。

启用桌面通知时，守护首次就绪会显示“Steam 连接保护”及“连接保护已就绪”，同一会话只提示一次。准备失败时，应用仍可启动，后台首次恢复后会补发就绪通知。这个提示对应 CM 规则状态，UU 的加速结果按第 9 节单独核对。目录代理的使用条件见 [实现逻辑](IMPLEMENTATION.md)。

如需明确分步观察安装后的启动层，可使用以下同等入口。在两个终端分别运行 Steam 与 UU，第一条会话可以保持运行：

```sh
fp_helper_dir="${XDG_DATA_HOME:-$HOME/.local/share}/felix-native-ux/v1"
python3 -B "$fp_helper_dir/routes.py" steam
```

另一个终端：

```sh
fp_helper_dir="${XDG_DATA_HOME:-$HOME/.local/share}/felix-native-ux/v1"
python3 -B "$fp_helper_dir/routes.py" uu
```

这就是普通图标背后的调度，不要求额外创建组合入口。调换两者启动顺序也可以；已有异网 Steam 需要从菜单正常退出后重开。

也可在应用启动前显式准备一次保护：

```sh
fp_helper_dir="${XDG_DATA_HOME:-$HOME/.local/share}/felix-native-ux/v1"
python3 -B "$fp_helper_dir/cm_guard.py"
```

这是启动/准备动作，不是只读查询。它可以通过短期桥接建立网络，随后应及时启动 Steam 或 UU 使用会话。日常普通图标会自动完成此步骤，无需额外运行。不要为了准备保护而在已加速状态下猜测或重置网络；需要取得原出口时先由用户在 UU 正常停止加速。

保护逻辑依次是：验证 keeper 身份并固定 namespace FD → 记录原 pasta 设备/网关/源地址 → 从 Valve CM 目录及严格日志候选发现合格端点并核对活跃 TCP → 添加目的 IPv4、TCP、目的端口精确规则 → 后台维护和按账本回收。

合格目录候选可提前保护，不要求先出现活跃连接。已走其他源地址的活跃连接暂缓接管。未发现的新端点、IPv6、下载 CDN 和游戏连接不在保证范围内；其他应用访问相同 IP+TCP 端口仍会命中。宿主路由不改动。详见 [实现逻辑](IMPLEMENTATION.md)。

## 7. 日常加速、切换和退出的顺序

1. 点击原来的 Steam 或 UU 图标；共享网络和 CM 保护自动准备。点哪一个只启动哪一个。
2. 打开另一方，它加入同一网络。Steam 的游戏保留各自的 Proton、前缀和启动参数，正常子进程链通常继承网络。
3. 在 UU 选择游戏、区服、路由模式和节点，开始加速；客户端显示成功后，再从该 Steam 启动游戏。
4. 换目标时，先正常退出当前游戏，在 UU 停止加速，再选新游戏/区服/节点并重新加速，然后启动新游戏。Steam 可以继续运行。
5. UU 停止或退出后，Steam 可继续通过 pasta 普通联网；已保护的 CM 连接保持原出口。所有共享网络成员退出后，wrapper/keeper 才回收会话并结束 pasta。

游戏连接随加速切换可能需要重新连接；CM 保护不保证游戏本身不断线。启动等待约 10～30 秒目前获用户接受，“无感”表示省去网络准备和额外入口，不表示零等待或自动识别游戏/选择节点。

## 8. 每一项完整功能是怎样实现的

| 功能 | 实现及对应组件 |
| --- | --- |
| Windows UU 可用虚拟网卡/路由 | 上游 WE-Proton 的 Wintun 和路由支持 |
| 同网与普通联网出口 | 上游 wrapper 管理共享会话，pasta 接宿主；UU 决定加速目标 |
| 删网卡、同名重建后正确识别 | Wine 0062 核对当前名称与索引，过滤失效记录 |
| 大路由表不因新校验明显回退 | Wine 0063 同次枚举复用成功转换，结束即释放，下次重查 |
| Steam 切换加速时在线连接保护 | `cm_guard.py`、`endpoints.py`、`policy.py` 提前固定精确 CM 端点出口 |
| 原 Steam/UU 图标、URI 和右键动作 | `enable.py`、`desktop.py`、`routes.py` 安装与调度 |
| 已有同网窗口唤出、异网实例拒绝 | `steam_window.py` 及 `routes.py`、历史网络入口检查 |
| 桌面/托盘/Dock 本机适配 | 历史运行器含 0061 等桌面模块，并配合入口辅助；不代表任意软件都兼容 |
| 自动诊断 | 运行器 `felix/observe.py` 等有限元数据观察；CM 独立状态和有界事件 |
| 有时限的进一步采样 | `src/live-watch/` 是另行按时限启动的诊断工具，本次部署不创建常驻采样服务 |
| 回退 | 桌面备份/恢复、CM 自有规则账本与退出清理 |

两张机制图和可点击源码导航见 [IMPLEMENTATION.md](IMPLEMENTATION.md)。0062/0063 不重写旧路由 API 的全部开销，CM 功能在 Python 层，本轮未重编 Wine。

## 9. 怎样确认每一层完成

只读状态命令：

```sh
fp_helper_dir="${XDG_DATA_HOME:-$HOME/.local/share}/felix-native-ux/v1"
python3 -B enable.py status
python3 -B "$fp_helper_dir/cm_guard.py" status
```

前者核对现有网络及实例冲突，后者读取 CM 持久化快照。`ready` 还应结合更新时间、进程身份与 keeper 命名空间复核；依赖检查通过、安装结束或快照存在都不能单独证明当前保护有效。

| 验收层面 | 应核对的结果 |
| --- | --- |
| 依赖及安装 | 材料与固定哈希匹配，运行器/配置/前缀归属正确，UU 安装完成后才切换图标 |
| 原图标体验 | Steam/UU 分别启动，保留 URI 和动作，已有窗口重复点击可处理，异网实例明确提示 |
| 网络归属 | 当前实际 Steam 与 UU 位于目标网络，使用当前身份，不照抄历史 PID 或 namespace 编号 |
| CM 策略 | 精确 CM IPv4/TCP 选原出口，同 IP 其他端口与 UDP 不受该规则影响，宿主路由/规则不变 |
| 用户复测 | 用户在 UU 正常切换所选目标时观察 Steam 在线状态，另行记录客户端成功及游戏实际连接效果 |
| 回退 | 桌面恢复尊重用户后续修改，CM 只清理自己登记的规则 |

代码回归从本节约定的 `src/native-ux` 目录执行：

```sh
python3 -B -m unittest discover -q
```

采集器解析回归从 `we/felix-proton/src/live-watch` 执行同一命令。策略用例需要可用的临时用户/网络命名空间，实际报告必须保留跳过数量。不要直接执行或导入 `watch.py` 做检查，它在顶层启动采集。

已有发布验证为原工作区及导出副本分别通过集成 64 项、采集器 16 项，均无失败、错误、跳过。本次完整指南整理只做静态命令/配置/链接与材料核对，没有重新安装或跑真实切换实验。路由命中、UU 界面成功和游戏实际改善是不同证据；异机及所有游戏/节点未全面验收。

## 10. 关闭、停用和回退

完整回退顺序为：**UU 正常停止加速 → 停止 CM 保护 → 恢复桌面入口 → 正常退出仍在共享网络内的应用 → 从恢复后的原入口重新打开。** 以下分别解释各动作。

仅退出 UU：在界面停止加速并正常退出，Steam 仍可保持运行；pasta 为整个共享网络继续服务。全部成员退出后会话才回收。

临时停止 CM：先在 UU 正常停止加速，再执行：

```sh
fp_helper_dir="${XDG_DATA_HOME:-$HOME/.local/share}/felix-native-ux/v1"
python3 -B "$fp_helper_dir/cm_guard.py" stop
```

它清理自有规则，下一次普通入口会重新准备。持续停用需把 `FELIX_STEAM_CM_GUARD=0` 放入实际启动器环境；仅在另一个终端 export 不一定影响桌面图标进程。

恢复原桌面入口，在当前源码/原解压的 `src/native-ux` 目录执行：

```sh
python3 -B enable.py restore
```

这只恢复入口，不停止 CM 守护，不会把已运行的 Steam 移回宿主网络，也不会删除前缀或账号；需按上面的完整回退顺序操作。文件若已被其他工具修改，恢复程序保留冲突。不要手工强杀 pasta 来代替回退。GitHub 文档或源码更新需要回退时，在对应分支新增 revert 提交。

## 11. 从源码重新构建与公开材料缺口

当前已验证运行器来自历史 `we-proton-ge11-11-31-desktop-netfix2`，含 0061 桌面模块与 0062/0063，再打包为 test.1。公开网络分支包含 0062/0063，没有完整的 0061 桌面补丁及已验收的全新运行器产物。

[`packaging/test.1/package-local.py`](../packaging/test.1/package-local.py) 校验并再打包已有历史二进制，不是从源码生成全部运行器的构建器。新编译产物的哈希通常不同，不能直接交给锁定原始 test.1 的安装器当作同一版本。

要提供不依赖本机历史归档的公开复现，还需补齐对应桌面模块的可公开源码、全部子模块和构建参数、SDK/工具链关联、许可与资产审核，再为新产物设置独立版本与校验并重新验收。历史源码归档含需审查的本机路径，尚未完成这条全新发布路径。

因此目前能完成的是“材料备齐后的完整功能部署”和代码/机制审阅；第三方仅靠 GitHub 下载就能构建并安装同等完整运行器仍是待完成事项。不得以删除校验、套用旧版本哈希或把普通上游运行器改名来代替。

UU 自由缩放暂缓；Steam Fossilize 历史 CPU 占用已归因并按用户要求保留设置。完整状态、验收与来源见 [CURRENT_STATE.md](CURRENT_STATE.md)、[TESTING.md](TESTING.md)、[PROVENANCE.md](PROVENANCE.md)。
