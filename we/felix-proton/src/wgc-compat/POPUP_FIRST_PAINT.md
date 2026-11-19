# 退出确认框呈现辅助程序

[popup_first_paint.py](popup_first_paint.py) 是 2026-11-19 原 Dock 版直播伴侣使用的 X11/XWayland 呈现脚本，按现用实现归档。它只筛选同一伴侣进程中符合窗口类、拥有关系、跳过任务栏属性及 280×162／32 位格式的退出确认框。窗口属性与绘制取样规则都在脚本内。

## 现用参数

| 常量 | 值 | 作用 |
| --- | ---: | --- |
| `CHECK_INTERVAL` | 8 毫秒 | 有待检查或正在接管的窗口时轮询 |
| `SETTLE_SECONDS` | **24 毫秒** | 深色面板和红色「确定」按钮连续符合判定的最短时间 |
| `MAX_WAIT` | 8 秒 | 接管超时后恢复原有不透明度 |

接管时将原不透明度状态记在窗口标记上，再暂设零不透明度。正常放行、结束观察和 `--release` 恢复时均用窗口标记核对归属。匹配与像素判定目前针对已验证的弹窗尺寸、X11 像素格式和主题。适配另一种尺寸或主题前，先在对应窗口独立验证。

## 接入测试会话

需要 Linux 的 `pidfd_open`、Python 3.10 以上、Python Xlib（Ubuntu 包名 `python3-xlib`），以及当前测试客户端所在的 X11 或 XWayland 会话。打开独立测试客户端后，从它的主窗查到本次的 X11 窗口 ID 与 `_NET_WM_PID`。例如用 `wmctrl -lp` 查窗口，再用 `xprop -id "$owner_xid" _NET_WM_PID WM_CLASS` 核对。

在同一个图形会话中，将 `source_dir` 指向本目录，`owner_pid` 和 `owner_xid` 对应同一测试主窗。在打开退出确认框前启动观察。

```bash
python3 -B "$source_dir/popup_first_paint.py" "$owner_pid" "$owner_xid"
```

原 Dock 的启动控制器用当前的主窗 XID 和 PID 启动单实例用户服务，继承该会话的 `DISPLAY` 和 `XAUTHORITY`（如已设置）。服务通过 `BindsTo` 和 `After` 绑定伴侣主服务。测试时可在观察终端用 Ctrl+C 停止辅助程序，它会尝试恢复仍接管的窗口。服务的 `ExecStopPost` 使用同一组参数加 `--release`，用于补做恢复。恢复入口要求原主窗和进程仍在。

```bash
python3 -B "$source_dir/popup_first_paint.py" "$owner_pid" "$owner_xid" --release
```

## 隔离复跑

[自有 X11 测试](test_popup_first_paint.py) 使用临时 Xvfb 显示，覆盖同尺寸异进程窗口不被接管、白底及只有深色面板时继续等待、按钮出现后恢复，以及正常停止和中断后的恢复。Ubuntu 上准备 `xvfb`、`xauth` 和 `python3-xlib` 后运行：

```bash
xvfb-run -a -s '-screen 0 1024x768x24 -nolisten tcp' \
  /usr/bin/python3 -B "$source_dir/test_popup_first_paint.py" -v
```

测试验证 X11 属性与绘制判定。原 Dock 合成帧和实测耗时见下方实机记录。8 秒异常沿用既有记录，成因仍待确认。

## 测量与回退

| 记录 | 内容 |
| --- | --- |
| [白底修复](../../docs/streaming/EXIT_DIALOG_WHITE_BACKGROUND.md) | 原 Dock 复测、现用流程和回退 |
| [分段计时](../../docs/streaming/EXIT_DIALOG_TIMING.md) | 窗口映射、内容首帧、放行和合成帧 |
| [24 与 12 毫秒对照](../../docs/streaming/EXIT_DIALOG_SETTLE_AB.md) | 保留 24 毫秒的实验依据 |
| [8 秒超时异常](../../docs/streaming/EXIT_DIALOG_TIMEOUT.md) | 超时放行后出现白底的单独记录 |

源码与测试由 Felix Li 在 OpenAI Codex 协助下完成，采用 [BSD-3-Clause](LICENSE)。
