# Felix 配对 0.1.0-preview.1

将 Steam 与网易 UU 的图标拖到一起，保存两个原有启动入口的配对。也可分别拖入对应位置或点击选择。**只需配对一次**：关闭工具或重启电脑后，仍用原来的 Steam、UU 图标启动；游戏、区服、路由模式和节点继续在 UU 中选择。

这是面向已配置好 Felix-Proton Steam/UU 共享网络环境的预览版。发行包提供配对工具、圆形 SVG 图标、源码和测试。Steam、UU、Proton 运行器和专用前缀按[完整配置说明](https://github.com/liyaomeng202114981-ops/Felix-Proton/blob/main/we/felix-proton/docs/FROM_ZERO.md)准备；历史固定 test.1 运行器未随本工具分发，单独安装工具不能从零获得完整加速环境。

## 环境要求

- Linux 图形桌面；当前主要验证 GNOME。
- 应用需要 Python 3.10+、PyGObject、GTK 4.10+、libadwaita 1.4+。
- 真正配对需要已安装且可用的 Felix-Proton 原生 Steam/网易 UU 集成、wrapper 和对应前缀。
- 首版仅支持有效的 `steam.desktop` 和 `uu-accelerator.desktop`。Flatpak/Snap Steam、其他平台及加速器尚未适配。

包内包含桌面入口处理模块，GUI 不依赖开发工作区。缺少集成配置时显示提示，配对不可用；工具不会安装客户端、运行器或初始化前缀。

## 下载与校验

从独立仓库的 [GitHub Releases](https://github.com/liyaomeng202114981-ops/Felix-Proton/releases) 下载 `felix-pairing-v0.1.0-preview.1` 对应文件，选择一种安装方式，并下载同一发行版的 `SHA256SUMS`。

| 文件 | 用途 |
| --- | --- |
| `felix-pairing-0.1.0-preview.1-linux.tar.gz` | 便携源码包，可直接运行或安装到当前用户目录 |
| `felix-pairing_0.1.0-preview.1_all.deb` | 兼容 Debian/Ubuntu 的系统安装包 |
| `SHA256SUMS` | 发行附件的 SHA-256 校验值 |
| `BUILDINFO.json` | 构建版本与文件哈希清单 |

在下载目录执行，确认下载的包显示 `OK`：

```sh
sha256sum --check --ignore-missing SHA256SUMS
```

## 便携运行与用户安装

```sh
tar -xzf felix-pairing-0.1.0-preview.1-linux.tar.gz
cd felix-pairing-0.1.0-preview.1
python3 -B app.py
```

需要在应用菜单添加“Felix 配对”时，在同一目录执行：

```sh
python3 -B install.py
```

安装只复制工具、图标和自己的菜单入口，不执行配对。已有首版记录在确认原配置未变化时兼容升级，原恢复备份保留，无需再拖一次。

已有用户级安装时，继续用此方法更新。建议同一用户选择一种安装方式：用户目录中已有的同 ID 菜单入口优先于系统入口，混用时可能仍打开旧版本。切换安装方式时，只处理本工具归属明确的菜单入口，保留配对恢复账本。

## Debian / Ubuntu 安装包

包管理器必须能提供上面的 GTK/libadwaita 版本。`all` 表示 Python 代码与架构无关，不代表所有发行版都已验证。

```sh
sudo apt install ./felix-pairing_0.1.0-preview.1_all.deb
```

从应用菜单打开“Felix 配对”，或运行 `felix-pairing`。系统安装不会替你配置 Steam/UU 的加速环境，升级工具也不要求重做已保存配对。

## 第一次配对

1. 打开工具，把 Steam 图标拖到网易 UU 图标上；也可分别放入两个位置，或点击选择。
2. 看到“入口已配对”后即可关闭工具，日常直接使用两个原图标。
3. 在 UU 中选择游戏、区服、路由模式和节点，再使用 Steam。

配对只影响后续启动，不能把已经运行在其他网络的客户端直接迁移过来。有冲突时，从客户端菜单正常退出，再从原图标打开。

也支持拖入当前已安装入口本身的 `.desktop` 文件，或使用“选择快捷方式”。工具核对有效条目身份；图标图片、任意同名文件、Windows `.lnk`/`.exe`、远程地址和未知应用不会被执行或导入。Dock/应用菜单跨窗口拖入取决于 Shell；工具内两个图标可直接互拖。

## 一次设置、关键变化与恢复

配对保存在持久目录中，日常启动不依赖工具常驻。语言设置、配置排版和 UU 内切换游戏/节点不会要求重配。更换前缀、运行器、wrapper、实际程序路径等关键设置，或原启动入口被外部修改后，再打开工具会要求检查。

- **已有连接**：配对只登记原 Steam/UU 连接，不重写入口。“移除管理记录”只停止工具管理，原网络设置继续保留。
- **工具新建的配对**：“解除配对”只恢复自己的两入口变更，保留图标、名称、Steam URI 和动作参数。
- **外部改动**：拒绝覆盖并保留恢复账本。不要删除恢复记录后反复配对。

工具不结束客户端、不拆除活动网络，也不调用旧版全量桌面恢复。两份入口通过写前账本、逐文件核对和失败补偿管理；它不是跨文件的内核原子事务，与外部编辑器仍存在核对到替换之间的竞争窗口。

## 卸载与数据位置

希望恢复入口时先在工具中“解除配对”。采用已有连接时的“移除管理记录”保留原设置，不能作为关闭原加速。

用户安装位于 `$XDG_DATA_HOME/felix-pairing-tool/`，默认 `~/.local/share/felix-pairing-tool/`。关闭工具后，按其中 `installation.json` 核对并移除自己的 `io.github.felixproton.Pairing.desktop`、图标和版本目录。

系统安装可使用：

```sh
sudo apt remove felix-pairing
```

账本位于 `$XDG_STATE_HOME/felix-pairing-tool/v1/pair.json`，默认 `~/.local/state/felix-pairing-tool/v1/pair.json`，目录私有、文件 0600。保留账本直到需要恢复的入口处理完；无需删除 Wine 前缀、账号状态或旧 native-ux 备份。真实配置、账本和日志不要上传仓库。

## SVG 图标

当前[圆形双环 SVG](assets/felix-pairing-round-v5.svg)仅含圆形与路径几何，三色平涂，无嵌入位图、外链或模糊滤镜。22px 离线渲染的可见范围已与本机 Steam 对齐，双环完整；实际 Dock 最终观感仍需用户复测。工具不会改变整个 Dock 的尺寸。

## 测试与构建

测试套件需要 Python 3.11+，应用最低为 3.10。实际结果与边界见 [TEST_RESULTS.md](TEST_RESULTS.md)。

```sh
python3 -B -m unittest discover -q
GSK_RENDERER=cairo python3 -B smoke_ui.py --snapshot-dir /absolute/private/output
python3 -B build_release.py --output-dir /absolute/output
```

GTK 检查使用模拟后台的控件回调，不等于实体鼠标跨应用拖拽、真实网络重配或游戏端到端加速通过。“入口已配对”、UU 已开始加速和游戏连接改善分别判断。

## 来源与许可

由 **Felix Li 在 OpenAI Codex 协助下**开发，在独立 [Felix-Proton](https://github.com/liyaomeng202114981-ops/Felix-Proton) 维护。新增代码采用 BSD-3-Clause，随包保留 [LICENSE](LICENSE) 与 [COPYRIGHT](COPYRIGHT)。桌面文件处理模块来自已有 native-ux 实现，保留来源和许可。

特别感谢 **SHORiN-KiWATA** 的 [WE-Proton](https://github.com/SHORiN-KiWATA/we-proton) 与 [shorin-proton-wrapper](https://github.com/SHORiN-KiWATA/proton-wrapper)，以及 [passt/pasta](https://passt.top/)、Proton、Wine、GE-Proton、DW-Proton 的贡献者。客户端名称、原图标和商标归原权利人，客户端、账号数据、运行器二进制和第三方品牌图标不随本工具分发。

接口依据 GTK 官方[拖放说明](https://docs.gtk.org/gtk4/drag-and-drop.html)、[GioUnix.DesktopAppInfo](https://docs.gtk.org/gio-unix/class.DesktopAppInfo.html) 和 [Adw.ToolbarView](https://gnome.pages.gitlab.gnome.org/libadwaita/doc/1-latest/class.ToolbarView.html) 文档。
