# Felix 配对 0.1.0-preview.1

Steam + 网易 UU 一次性配对工具的首个预览发行版。将两个应用图标拖到一起，保存原启动入口关联；完成后关闭工具，日常仍用两个原图标。游戏、区服、路由模式和节点继续在 UU 中选择。

本版包含：

- 图标互拖、两个位置分别拖入、点击选择和有效 .desktop 入口导入。
- 已有连接幂等登记；新配对的两入口备份、失败补偿、恢复及外部改动保护。
- 持久配对；语言/排版等普通变化不要求重配，关键连接配置变化时要求检查。
- 原生圆形双环 SVG：三色平涂、746 bytes，22px 可见范围与本机 Steam 对齐。
- 便携源码包、Debian/Ubuntu all 安装包、源码和测试、许可、SHA256SUMS 与 BUILDINFO.json。

## 下载与运行

下载需要的 .tar.gz 或 .deb，以及同一发行版的 SHA256SUMS，在下载目录执行：

```sh
sha256sum --check --ignore-missing SHA256SUMS
```

便携包解压后进入 felix-pairing-0.1.0-preview.1，运行 `python3 -B app.py`；需要用户菜单入口时运行 `python3 -B install.py`。已有用户级安装建议沿用此方式更新，避免用户入口遮蔽系统 .deb 入口。

应用需要 Python 3.10+、PyGObject、GTK 4.10+、libadwaita 1.4+。真正配对需要预先配置好的 Felix-Proton 原生 Steam/UU 共享网络环境。固定历史 test.1 运行器、Steam、UU 和前缀未随此工具分发；仅安装配对工具不能从零获得完整加速环境。

“移除管理记录”只停止管理原有连接；“解除配对”只恢复本工具修改的入口。升级或卸载均应保留需要的配对恢复账本。

## 验证范围

本次 **32 项隔离测试通过**（26 项配对功能、6 项发行构建），解压包内复跑通过；重复构建、Debian 内容与依赖、空配置环境用户安装及缺配置界面检查通过。详情见[该版本测试报告](https://github.com/liyaomeng202114981-ops/Felix-Proton/blob/felix-pairing-v0.1.0-preview.1/we/felix-proton/src/pairing-tool/TEST_RESULTS.md)。GTK 检查使用模拟后台和空配置环境，不代表实体鼠标跨应用拖拽、实际 Dock 纹理或真实游戏加速验收。

## 对应源码与重建

便携包同时是本版的完整工具源码分发，`BUILDINFO.json` 列出每份源码的 SHA-256。解压后运行 `python3 -B build_release.py --output-dir ./rebuilt` 可重建工具附件；测试套件需要 Python 3.11+，构建 .deb 还需要 `dpkg-deb`。默认固定 SOURCE_DATE_EPOCH=0，同一受测环境中的完整重建结果已逐字节核对。源码与附件共同保留许可和版权信息。

预览版仅适配 Steam + 网易 UU，尚无异机全面验收；入口配对就绪与 UU 开始加速、游戏连接改善分别判断。

感谢 **SHORiN-KiWATA** 的 WE-Proton 与 proton-wrapper，及 passt/pasta、Proton、Wine、GE-Proton、DW-Proton 的贡献者。由 **Felix Li 在 OpenAI Codex 协助下**开发；BSD-3-Clause 源码、原作者和许可随包保留。
