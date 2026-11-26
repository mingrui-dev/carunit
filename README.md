# carunit

车机 Android 调试小工具：把车机上最常做的几件事（看设备、查前台应用、截图、装包、导 APK、抓日志、改调试开关）收成一条命令。

单个 `.py` 文件、纯标准库、Windows 控制台友好，适合放在 U 盘里跟 `adb.exe` 一起带走。

## 为什么用

车机上折腾 ADB 的常见痛点，它都替你处理掉了：

- 命令太长记不住：`adb shell dumpsys window | grep mCurrentFocus` 之类，现在一条 `carunit.py top`
- 截图要来回 pull：直接 `carunit.py shot`，按时间戳存到 `screenshots/`
- 装一堆 APK 要一条条敲：`carunit.py install D:\apks\` 整个目录批量装，逐个报成功/失败
- 想知道某个车机自带应用的包名、想备份它的 APK：`top` + `export`
- 抓日志被系统日志淹没：`logcat --package <包名>` 只看目标进程，默认不清空设备日志
- 调完忘了恢复动画/常亮：`setup` 修改前自动备份，可用 `setup --restore` 一键还原

## 环境要求

- Python 3.8+
- adb（Android platform-tools）

Windows 免安装用法：把 `adb.exe` 和 `carunit.py` 放在同一个文件夹里，双击命令行进目录执行即可。程序会优先使用同目录的 `adb.exe`，找不到时再查 PATH；也可以用 `--adb` 显式指定路径。

## 常用命令

| 命令 | 作用 |
| --- | --- |
| `python carunit.py devices` | 列出已连接设备（含型号） |
| `python carunit.py info` | 型号 / 系统版本 / 分辨率 / DPI |
| `python carunit.py top` | 当前前台应用包名与 Activity |
| `python carunit.py shot [目录]` | 截图并保存到本地 |
| `python carunit.py install <APK或目录>...` | 批量覆盖安装；加 `--grant-permissions` 才预授权限 |
| `python carunit.py export <包名>` | 导出 APK；遇到 split APK 会保存 base 和全部分片 |
| `python carunit.py logcat --package <包名> --seconds 15 -o log.txt` | 采集日志；默认不清空，加 `--clear` 才清空 |
| `python carunit.py crash` | 导出崩溃缓冲区日志 |
| `python carunit.py setup` | 关闭动画、屏幕常亮、延长超时，并自动备份原值 |
| `python carunit.py setup --restore` | 从备份恢复设置 |
| `python carunit.py tcpip --port 5555` | 切无线调试（需先 USB 连接） |
| `python carunit.py connect 192.168.1.9:5555` | 连接无线调试地址 |

多设备时用 `--serial` 指定：

```bash
python carunit.py --serial 0123456789ABCDEF shot
```

## 设置备份与恢复

`setup` 会在修改前读取原值并写入 `carunit-setup.backup.json`。重复执行不会覆盖第一次备份；不同设备建议使用不同备份文件：

```bash
python carunit.py setup --dry-run
python carunit.py setup
python carunit.py setup --restore
python carunit.py setup --state-file carunit-A.json
python carunit.py setup --state-file carunit-A.json --restore
```

恢复操作只改回备份中记录的动画、充电常亮和屏幕超时，不会重置其它系统设置。

## 导出 split APK

普通单 APK 仍导出为 `apks/<包名>.apk`。如果应用包含 split APK，则会保存到 `apks/<包名>/`，包含 `base.apk` 和全部分片，避免只备份到主体而遗漏资源。

## 车机实战提示

- **先开 USB 调试**：车机设置里通常藏在「关于本机」连点版本号后出现的开发者选项里，部分车型需要工程模式密码。
- **权限受限是常态**：`setup` 里个别项可能因为车机策略失败，脚本会逐条报告，不影响其它命令；可用 `--restore` 恢复已备份项。
- **日志清理**：`logcat` 默认保留设备原有日志，只有显式加 `--clear` 才会清空缓冲区。
- **截屏失败**：部分车机禁用了 `exec-out`，会提示不是 PNG。可以先 `adb shell screencap -p /sdcard/x.png` 再 `adb pull`。
- **无线调试**：绝大多数车机没有 WiFi，只能 USB。带 WiFi 的车型可先 `tcpip` 再 `connect`。
- **`pidof` 不可用**：老系统可能没有 `pidof`，此时用不带 `--package` 的 `logcat` 再配合 `--grep`。
- **抓不到日志**：先确认应用在运行，`carunit.py top` 能看到它即可。

## 开发

```bash
python -m unittest test_carunit -v
python tools/build_release.py
```

测试全部基于注入的假 adb，不需要真机；CI 在 ubuntu / windows 的 Python 3.10 与 3.12 上跑同一套用例，并单独校验发布包。打包脚本会检查 ZIP 中的 UTF-8 中文文件名、GBK 离线说明、CRC 和 SHA256，产出 `.zip` 与 `.sha256.txt`。

代码结构：

- `carunit.py`：CLI、adb 封装、纯函数解析器、各子命令
- `test_carunit.py`：解析器与命令流程的单元测试
- `tools/build_release.py`：可重复的离线发布包构建与校验

## 免责声明

本工具仅用于调试**你本人拥有**、或**已获得设备所有者明确授权**的 Android 设备（含车机）。

- 不包含任何绕过应用风控、破解、刷量或规避检测的功能
- 请自行确认使用行为符合当地法律法规、车辆保修条款与目标应用的用户协议
- 由使用者自行承担使用后果

## License

MIT（如需其它协议请替换本文件）