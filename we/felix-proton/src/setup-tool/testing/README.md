# 从零安装的隔离实测

这里是需要真实运行器的手工集成测试，不属于 `unittest` 的模拟用例。只在一次性 case 中运行，不使用游戏、真实 Steam 账号或 UU 账号，也不操作宿主鼠标。

`isolated_prefix.py` 保持 HOME 的字符串不变，在私有挂载命名空间中把其内容换成新的 case/home。外层 user/net 命名空间只有 lo、测试 dummy 和文档网段默认路由，没有宿主物理网卡或外网。内层 bwrap 再隔离 user/PID/mount/IPC/UTS，根目录只读，/tmp、/run 和 XDG 独立。PID 命名空间结束时所有测试后代一并退出。SLR4 只读，原 `.ref` 锁文件通过单独的私有 inode 替代。

测试器需要 Python 3.11+，当前用户可以使用 unshare/bwrap/TUN、dbus-run-session、SLR4、固定运行器归档、已核验的 wrapper/pasta 和 Xvfb；宿主不要以 root 运行。`--xvfb` 可以指向系统程序，也可指向从发行版官方包仓库校验下载后仅解包的程序。程序的版本和动态库属于测试环境，需要单独记录；不随本项目重新分发。

先在对应 Steam Runtime SDK 中离线编译自有 `prefix_probe.c`：

```sh
x86_64-w64-mingw32-gcc -O2 -static -municode prefix_probe.c -o prefix_probe.exe -liphlpapi -lws2_32
```

然后准备路径（下方参数均需改为本机实际文件，case 必须尚不存在）：

```sh
python3 -B isolated_prefix.py run \
  --case /var/tmp/felix-clean-install-unique \
  --archive /absolute/felix-proton-uu-test-0.1.0-test.1.tar.zst \
  --wrapper /absolute/shorin-proton-wrapper \
  --pasta /absolute/pasta \
  --runtime /absolute/SteamLinuxRuntime_4 \
  --native-source /absolute/extracted-kit/src/native-ux \
  --probe /absolute/prefix_probe.exe \
  --xvfb /absolute/Xvfb
```

默认 `prefix` 模式验证固定归档安装、新配置/前缀、wrapper/SLR 的 wineboot，以及真实 PE 文件 I/O 和网络适配器 API 的启动/退出。原生 Steam 使用无账号替身，不会启动宿主 Steam。

在相同命令后加 `--mode install --uu-installer /absolute/官方安装包.exe --timeout 700`，测试完整新引导。官方安装程序不随包提供；操作者只能在该私有 X11 显示内完成安装，不登录账号。case 中的 `private-gui-environment.json` 记录显示和认证路径，任何输入前都须核对私有进程/命名空间、当前窗口标题、类名、安装器身份及位置，不能把这些值用于宿主桌面。测试器不会自动点击未知安装器。

完整安装返回成功后，`post_install.py` 才核对原品牌图标和 Steam URI、status、重复安装保持配置/入口、原生替身与 UU keeper 的同网络关系、单个合成 IPv4/TCP CM 端点的保护与回收，以及实际配对后台采用/停止管理和入口恢复。合成 CM 端点为文档地址；它不是 Valve 目录或真实游戏连接。输入和桌面图片仅留私有 case。

每轮先复制只读源码快照，记录逐文件 SHA-256、材料哈希、命令、退出和宿主 IPv4 规则/路由前后对照。失败代次保留，不能将 prefix 成功、官方客户端安装成功与完整新引导成功合并计数。Xvfb 结果不等于 GNOME/Dock、多屏、所有发行版、真实节点或游戏端到端验收。
