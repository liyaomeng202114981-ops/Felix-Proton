# Felix-Proton 从零安装 0.1.0-preview.1

首次提供从新环境安装原生 Steam + Windows 网易 UU 集成所需的固定运行器、下载引导、前缀初始化和原图标接入。之前配对工具要求先自行准备底层环境，本版补齐这些安装材料与流程。

## 普通使用者下载什么

下载 `felix-proton-setup-0.1.0-preview.1-linux.tar.gz` 和 `SHA256SUMS`。运行器、wrapper和pasta由引导按固定SHA自动下载；构建源码附件无需下载即可使用。

先安装原生Steam并打开一次初始化，再正常退出；从UU官方取得Windows安装程序。解压引导包后执行：

```sh
python3 -B src/setup-tool/setup.py check
python3 -B src/setup-tool/setup.py install --uu-installer "$HOME/Downloads/UU-official-setup.exe"
```

把安装器路径换成实际官方文件，按其窗口完成安装。之后继续用原Steam/UU图标，目标/区服/节点和路由模式在UU内选择，配对工具可一次登记既有连接并关闭。

[完整依赖、校验、离线材料与回退步骤](https://github.com/liyaomeng202114981-ops/Felix-Proton/blob/felix-proton-setup-v0.1.0-preview.1/we/felix-proton/packaging/fromzero/INSTALL.md)

## 环境与验证

x86-64 Linux图形桌面、原生Steam、Python3.10+、GTK4.10+、libadwaita1.4+、TUN及非特权user/net namespace。自动pasta二进制需要glibc2.38+。本版暂不支持Flatpak/Snap Steam；使用者自行取得Steam/UU，不分发客户端或账号。

155项代码/源码/打包测试通过。使用安装包解压代码和真实官方UU安装器，在空HOME/全新prefix、独立user/net/PID、私有Xvfb及SLR中实际验证安装、原图标、重复执行、原生替身同网、精确合成CM选路/清理、配对采用/移除和入口恢复，宿主路由保持。实际Steam/UU账号登录、真实节点/游戏和异机图形兼容未在本轮验收。[完整测试与边界](https://github.com/liyaomeng202114981-ops/Felix-Proton/blob/felix-proton-setup-v0.1.0-preview.1/we/felix-proton/docs/SETUP_TEST_RESULTS.md)

## 运行器与对应源码

运行器为原SHA锁定的历史`0.1.0-test.1`重打包，带0061桌面兼容和0062/0063网络补丁，未在本轮全量重新编译。随版提供修改后Wine、基础构建树、原上游源码、115份必要依赖源档及独立wrapper/pasta源档；`SOURCE_INDEX.json`、`NETWORK_SOURCES.json`和两份NOTICES说明对应关系与许可，所有附件由SHA256SUMS覆盖。源码附件用于研究/重建，安装时不需要下载1.3GB依赖源码包。

感谢 **SHORiN-KiWATA** 的WE-Proton与proton-wrapper，以及Wine/Proton、GE-Proton、DW-Proton、passt/pasta及各组件贡献者。**Felix Li，with OpenAI Codex assistance**维护本集成，保留作者、Git历史与原许可；各组件不统一改为Felix许可证。
