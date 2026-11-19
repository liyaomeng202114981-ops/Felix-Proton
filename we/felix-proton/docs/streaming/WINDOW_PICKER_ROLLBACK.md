# Ubuntu 窗口选择修复的回退方法

## 恢复上一套选窗组件

1. 结束当前测试或工作中的共享，正常退出伴侣。确认本次会话的选窗辅助程序与窗口采集进程已退出。
2. 用安装前的同批备份恢复前缀和运行载荷里的两份 WGC DLL、选窗辅助程序、Unix 桥接库与启动控制器。移除本次新增的 `window-stream-interactive`。保留备份和上一套窗口进程，便于以后重新接入。
3. 从原 Dock 图标重开，在空测试场景中重新授权一扇窗口并核对预览。回退到上一套后，继续按上一套的窗口选择方式操作。

有本机配套备份的安装可用当次的 `install_picker.py rollback` 一次恢复匹配组件。该脚本和批次备份随本机安装留存。声音、直连和桌面入口配置不参与组件替换。

## 临时恢复画面

原 Dock 图标右键可选择「UnityCapture 回退」，在伴侣使用 **Unity Video Capture** 摄像头素材。该入口共享的是整桌面，使用前可按需要整理可见内容。

[匹配组件的隔离构建](../../src/wgc-compat/README.md#隔离构建)

[选窗流程](WINDOW_PICKER_FLOW.md) · [临时共享的清理](WINDOW_PICKER_CLEANUP.md) · [上一套窗口同步进程回退](WINDOW_CAPTURE_ROLLBACK.md)
