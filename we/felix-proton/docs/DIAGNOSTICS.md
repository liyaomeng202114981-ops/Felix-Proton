# 只读诊断与回退

先确认本机安装配置、日志时间范围与进程身份。不要照抄历史 PID、网卡索引、命名空间编号或端点地址。

## 查询保护状态

普通安装的活跃配置指针位于 `~/.config/felix-native-ux/active.json`。已安装启动层通常位于 `~/.local/share/felix-native-ux/v1/`。以下命令只读：

```sh
python3 -B ~/.local/share/felix-native-ux/v1/cm_guard.py status
```

`status` 返回持久化快照。判断服务当前是否生效，还需结合更新时间、进程 UID、启动时间、可执行命令和 keeper 命名空间核对。单独出现 `ready` 或 PID 存在不足以确认；读取失败也不等于 Steam 已掉线。不要把无参数启动、`stop`、`enable.py` 或 `routes.py` 当作状态查询。

状态位于 `$XDG_RUNTIME_DIR/felix-steam-cm/<prefix-hash>/status.json`；有界事件与归属记录位于 `$XDG_STATE_HOME/felix-steam-cm/<prefix-hash>/`，后者默认使用 `~/.local/state`。源代码迁移和公开发布不会自动升级已安装副本。

## 解释已有证据

共享网络、UU 网卡存在、路由命中和用户实际连接改善是不同证据。没有游戏实际流量时，只报告预期路径检查结果。不要把某次 HTTP 成功或任意 TCP/443 连接当作 CM 健康证明。

被动采集器的四小时历史观察已经结束；本源码发布不启动新的后台监控。不要直接执行或导入 `src/live-watch/watch.py` 做语法检查：它在顶层启动采集。运行现有测试或使用 AST 解析即可。

先前内核崩溃的用户排查结论见 [当前状态](CURRENT_STATE.md)。历史 Fossilize CPU 归因不表示当前仍有相同负载，用户已决定保留设置。

原始 Steam/UU 日志、账号、完整命令行、远端端点集合与配置只留本机；对外只整理固定事件、计数、错误分类和脱敏时间范围。

## 运行时回退

临时关闭 CM 保护前，先在 UU 界面正常停止加速，再运行：

```sh
python3 -B ~/.local/share/felix-native-ux/v1/cm_guard.py stop
```

它只清理该守护程序登记的规则；下一次普通入口会重新启用。持续停用可在启动器环境设置 `FELIX_STEAM_CM_GUARD=0`。

恢复桌面入口，在经过核对的原解压目录执行：

```sh
python3 enable.py restore
```

备份默认位于 `~/.local/state/felix-native-ux/`。若条目已被其他工具修改，恢复程序会保留冲突。完整依赖及安装说明见 [普通图标使用说明](../src/native-ux/README.md)。
