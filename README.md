# carunit

车机 Android 调试小工具：把车机上最常做的几件事（看设备、查前台应用、截图、装包、导 APK、抓日志、改调试开关）收成一条命令。

单个 `.py` 文件、纯标准库、Windows 控制台友好，适合放在 U 盘里跟 `adb.exe` 一起带走。

## 为什么用

车机上折腾 ADB 的常见痛点，它都替你处理掉了：

- 命令太长记不住：`adb shell dumpsys window | grep mCurrentFocus` 之类，现在一条 `carunit.py top`
- 截图要来回 pull：直接 `carunit.py shot`，按时间戳存到 `screenshots/`
- 装一堆 APK 要一条条敲：`carunit.py install D:\apks\` 整个目录批量装，逐个报成功/失败
- 想知道某个车机自带应用的包名、想备份它的 APK：`top` + `export`
- 抓日志被系统日志淹没：`logcat --package <包名>` 只看目标进程
- 调完忘了恢复动画/常亮：`setup` 一键设置调试参数

## 环境要求

- Python 3.8+
- adb（Android platform-tools）

Windows 免安装用法：把 `adb.exe` 和 `carunit.py` 放在同一个文件夹里，双击命令行进目录执行即可；也可以把 adb 加进 PATH。

## 常用命令

| 命令 | 作用 |
| --- | --- |
| `python carunit.py devices` | 列出已连接设备（含型号） |
| `python carunit.py info` | 型号 / 系统版本 / 分辨率 / DPI |
| `python carunit.py top` | 当前前台应用包名与 Activity |
| `python carunit.py shot [目录]` | 截图并保存到本地 |
| `python carunit.py install <APK或目录>...` | 批量安装，`-r -g` 覆盖安装并预授权限 |
| `python carunit.py export <包名>` | 把已安装的 APK 拉回本地 |
| `python carunit.py logcat --package <包名> --seconds 15 -o log.txt` | 采集指定时长的日志，可按包名/正则过滤 |
| `python carunit.py crash` | 导出崩溃缓冲区日志 |
| `python carunit.py setup` | 关闭动画、屏幕常亮、延长超时 |
| `python carunit.py tcpip --port 5555` | 切无线调试（需先 USB 连接） |
| `python carunit.py connect 192.168.1.9:5555` | 连接无线调试地址 |

多设备时用 `--serial` 指定：

```bash
python carunit.py --serial 0123456789ABCDEF shot
```

## 车机实战提示

- **先开 USB 调试**：车机设置里通常藏在「关于本机」连点版本号后出现的开发者选项里，部分车型需要工程模式密码。
- **权限受限是常态**：`setup` 里个别项可能因为车机策略失败，脚本会逐条报告，不影响其它命令。
- **截屏失败**：部分车机禁用了 `exec-out`，会提示不是 PNG。可以先 `adb shell screencap -p /sdcard/x.png` 再 `adb pull`。
- **无线调试**：绝大多数车机没有 WiFi，只能 USB。带 WiFi 的车型可先 `tcpip` 再 `connect`。
- **`pidof` 不可用**：老系统可能没有 `pidof`，此时用不带 `--package` 的 `logcat` 再配合 `--grep`。
- **抓不到日志**：先确认应用在运行，`carunit.py top` 能看到它即可。

## 开发

```bash
python -m unittest test_carunit -v
```

测试全部基于注入的假 adb，不需要真机；CI 在 ubuntu / windows 的 Python 3.10 与 3.12 上跑同一套用例。

代码结构：

- `carunit.py`：CLI、adb 封装、纯函数解析器、各子命令
- `test_carunit.py`：解析器与命令流程的单元测试

## 免责声明

本工具仅用于调试**你本人拥有**、或**已获得设备所有者明确授权**的 Android 设备（含车机）。

- 不包含任何绕过应用风控、破解、刷量或规避检测的功能
- 请自行确认使用行为符合当地法律法规、车辆保修条款与目标应用的用户协议
- 由使用者自行承担使用后果

## License

MIT（如需其它协议请替换本文件）