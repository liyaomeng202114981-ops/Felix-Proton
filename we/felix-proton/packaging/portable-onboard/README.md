# UU 游戏加速（Steam）· 本地引导器预览 1

这个向导用于 Felix Proton UU 0.1.0-test.1，面向 x86-64 Linux 上的原生 Steam。它把安装时的路径探测、独立网络设置和日常启动做成一个入口。桌面上的原 Steam 仍适合普通直连使用。Flatpak 和 Snap 版 Steam 不在这个预览的验证范围内。

## 首次使用

1. 准备已初始化的原生 Steam、Python 3.10+、zstd、[shorin-proton-wrapper](https://github.com/SHORiN-KiWATA/proton-wrapper)、支持 `--no-pidns` 的 [pasta（passt）](https://passt.top/passt/about/) 以及 [网易 UU 官方 Windows 安装程序](https://uu.163.com/)。Ubuntu 等发行版如何安装 wrapper，请看原作者的 [Releases](https://github.com/SHORiN-KiWATA/proton-wrapper/releases)。命名空间和 TUN 设备需在本机可用。wrapper 可能在首次使用时下载 Steam Linux Runtime，需要网络连接。
2. 解压本地预览包。它已把 `felix-proton-uu-test-0.1.0-test.1.tar.zst` 放在引导器旁，内部的运行器包保留压缩状态。若只取得引导器源码，也可以把同名运行器包放在引导器旁、它的上一级目录或 `~/Downloads/`。在有 `start.py` 的目录运行一次：

   ```sh
   python3 start.py
   ```

   程序检查依赖和归档校验值，定位 Steam，安装独立运行器并创建应用菜单入口。若提示缺少依赖，按提示安装后重跑即可。可先执行 `python3 start.py check` 查看基础条件。Ubuntu 的 AppArmor 策略可能限制用户命名空间，静态检查通过后仍需验证真实会话。
3. 打开应用菜单中的 **UU 游戏加速（Steam）**。首次会提示选取官方 UU 安装程序并交互完成安装。若当前 Steam 运行在其他网络，请先正常退出，再点统一入口。登录 UU 后，选好要玩的游戏、区服和支持路由模式的节点。

## 以后怎么玩

每次从同一个 **UU 游戏加速（Steam）** 入口启动，向导会检查 UU 和原生 Steam 的网络归属。切换普通 Steam 游戏时，在 UU 停止当前加速，再选择下一款即可；游戏从同一 Steam 客户端启动，一般不需要逐个改游戏的启动参数。确认“相同网络”只证明入口工作正常。是否连上 UU 节点、目标流量和延迟表现需要另行实测。

常规状态使用通知显示，安装文件选择需要 zenity 或交互终端。没有图形选择器时可以在终端运行：
```sh
python3 start.py open --uu-installer "/路径/网易 UU 安装程序.exe"
```
对选定的可执行文件会检查 PE 格式及 SHA-256；应从网易官方取得安装文件。超时、切错入口或加速异常时，测试版运行器的本地时间线仍能用于排查。应用菜单右键有“标记刚才异常”。可用 `python3 start.py remove` 移除本向导创建的快捷方式，前缀和个人数据保留。

## 项目来源与验证范围

[WE-Proton](https://github.com/SHORiN-KiWATA/we-proton) 和 [proton-wrapper](https://github.com/SHORiN-KiWATA/proton-wrapper) 来自 SHORiN-KiWATA。虚拟网卡、UU 路由兼容和按前缀创建或加入独立网络使用上游工作。Felix Li 在 OpenAI Codex 的协助下开发了接口失效和路由枚举修复、启动保护、诊断以及本向导。[网络补丁及实验](https://github.com/SHORiN-KiWATA/we-proton/pull/1)

这是便携安装和启动流程的源码预览。验证范围为临时用户目录下的安装、目标目录识别、冲突和入口状态检查；另一台真实 Linux 电脑上的节点和游戏连接仍待验证。本机之前出现过内核定时器 panic，重试中又出现相似警告，触发原因尚未确定。这一版向导的验证没有重跑该场景。这个本地预览包包含引导器和固定校验值的 test.1 运行器，供本机试用。公开分发前还需完成异机实测，并整理与二进制对应的源码、保留各组件许可。此前历史源码归档中含有本机开发路径，应先清理并复核。
