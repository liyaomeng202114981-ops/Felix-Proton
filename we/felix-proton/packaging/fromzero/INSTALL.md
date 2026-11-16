# Felix-Proton 从零安装预览版 0.1.0-preview.1

面向 x86-64 Linux 的原生 Steam + Windows 网易 UU。安装引导下载并校验固定运行器、wrapper 和 pasta，创建专用新前缀、打开官方 UU 安装程序，完成后接入原 Steam/UU 图标并安装“Felix 配对”。日常继续使用原图标，游戏、区服、节点和路由模式在 UU 内选择。

Steam、UU 安装程序和账户不随包分发。请先从官方渠道安装原生 Steam，打开一次完成初始化后从菜单正常退出；下载官方 Windows UU 安装程序。当前不支持 Flatpak/Snap Steam。

## 系统准备

需要 Python 3.10+、Bash、zstd、util-linux、iproute2、可用的非特权 user/net namespace 与 `/dev/net/tun`；配对界面需要 GTK 4.10+、libadwaita 1.4+、PyGObject。主要测试环境为 GNOME/x86-64。系统策略不允许命名空间时，检查命令会报告具体限制，不修改系统安全策略。

兼容 Debian/Ubuntu 系统可安装基础依赖（各包仍需满足上面的最低版本）：

```sh
sudo apt install python3 python3-gi python3-cairo gir1.2-gtk-4.0 gir1.2-adw-1 zstd xz-utils curl ca-certificates util-linux iproute2 wmctrl x11-utils libnotify-bin desktop-file-utils zenity locales
sudo locale-gen zh_CN.UTF-8
```

wrapper 会准备 Steam Linux Runtime，首次运行需要网络和额外磁盘空间。安装固定运行器需要至少 2 GiB 临时空间，另须预留前缀、Steam Runtime 与客户端的空间。不要以 sudo/root 运行下面的用户安装命令。

随发行版提供的 x86-64 pasta 二进制要求 glibc 2.38+；已有兼容 pasta 的用户可显式用 `--pasta /绝对路径/pasta`。这不是面向任意 Linux 发行版或非 x86-64 架构的通用安装包。

## 下载、检查和安装

从本仓库的 `felix-proton-setup-v0.1.0-preview.1` 发行页下载安装引导压缩包与 SHA256SUMS，放在同一下载目录：

```sh
sha256sum --check --ignore-missing SHA256SUMS
tar -xzf felix-proton-setup-0.1.0-preview.1-linux.tar.gz
cd felix-proton-setup-0.1.0-preview.1
python3 -B src/setup-tool/setup.py check
python3 -B src/setup-tool/setup.py install --uu-installer "$HOME/Downloads/UU-official-setup.exe"
```

把最后一行的路径改为自己从官方取得的 Windows UU 安装程序。按安装窗口完成安装，等待引导报告完成；未确认客户端安装完成前，不会切换 Steam 入口。之后从两个原图标打开应用，在 UU 登录并选择加速目标；可打开“Felix 配对”登记已有连接一次，工具无需常驻。

本版下载的固定运行器为历史 `0.1.0-test.1`，带 0061 桌面兼容和 0062/0063 网络补丁。它是受测历史构建的原样重打包，不是本轮全量重新编译；归档和内部身份均校验，不能用任意 Proton 改名替代。

## 恢复与验证边界

使用 `python3 -B src/setup-tool/setup.py status` 查看状态，使用 `python3 -B src/setup-tool/setup.py restore` 按归属记录恢复本工具修改的桌面入口。恢复入口不会迁移已运行的 Steam、结束应用或删除前缀；需要退出时用应用自身菜单。保留配对与入口恢复账本，不删除账号前缀来重试安装。

当前代码测试、干净前缀/网络测试和仍待异机、真实游戏验证的范围在随包测试报告中分别记录。“入口已配对”、CM 保护就绪、UU 开始加速和游戏实际连接改善是不同证据。

运行器、修改后 Wine、基础构建与依赖的对应源码及各自许可证随发行版单独提供；安装使用者不必下载全部源码附件。感谢 SHORiN-KiWATA 的 WE-Proton/proton-wrapper、Wine/Proton 和 passt/pasta 等贡献者。Felix Li 在 OpenAI Codex 协助下维护本集成，保留上游作者和许可。
