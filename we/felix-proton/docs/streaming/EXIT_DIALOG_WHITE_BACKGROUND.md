# 退出确认框白底修复

2026-11-19，Ubuntu GNOME Wayland 上的原 Dock 版直播伴侣已启用此修复。目标是让「确认退出吗？」首次显示时就有完整的深色面板和红色「确定」按钮。

## 现象

截图对应一个 280×162 的退出确认框。X11 原始像素先出现不透明白底，再切为深色面板。部分测试中，同一 Win32 窗口在这个过程中换了 X11 窗口 ID。关闭 GPU 合成，以及另一组关闭遮挡和后台渲染节流的参数，均仍采到白色首帧。白底的单一上游成因仍待确认。

Electron 的 `BrowserWindow` 可由应用设置 `show: false` 并在 `ready-to-show` 时显示，也可以指定与主题相符的 `backgroundColor`。当前兼容措施放在客户端外部的 X11 呈现层。[Electron 首帧说明](https://www.electronjs.org/docs/latest/api/browser-window#showing-the-window-gracefully)

## 实现

- 原 Dock 的本机启动控制器运行 `popup_first_paint.py`。仅筛选本伴侣进程内同类的 280×162、32 位 ARGB 窗口，要求其拥有窗同进程同类且尺寸符合主窗条件，弹窗带有跳过任务栏标记。
- 对匹配的窗口暂时设置 X11 窗口不透明度为零，每 8 毫秒检查画面。深色面板与红色确认按钮连续满足判定至少 24 毫秒后，恢复原不透明度。关闭辅助进程时也恢复，用户服务另有退出后的恢复入口。
- 若 8 秒内未确认完整画面，恢复原不透明度以放行弹窗。[超时异常与处理](EXIT_DIALOG_TIMEOUT.md)

## 原 Dock 复测

三次退出确认框测试采到 19 个原始白底样本，采样时窗口均为零不透明度。三次首次可见的完整 X11 样本分别为 95.4、130.3 和 191.9 毫秒。测试通过「取消」关闭确认框，保留主会话。临时不透明度的恢复另经验证。此次只验证退出弹窗，全程不开播。

[现用源码](../../src/wgc-compat/popup_first_paint.py) · [接入与隔离复跑](../../src/wgc-compat/POPUP_FIRST_PAINT.md)

## 回退

停止用户服务 `felix-douyin-exit-dialog-presentation.service`，通过服务退出钩子恢复尚在接管的窗口，再换回本机保存的上一份启动控制器。伴侣主进程可继续运行。[分段计时](EXIT_DIALOG_TIMING.md) · [保留 24 毫秒的对照依据](EXIT_DIALOG_SETTLE_AB.md)
