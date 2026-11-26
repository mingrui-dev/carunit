#!/usr/bin/env python3

import hashlib
import os
import re
import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GBK_README = """carunit {version} 离线使用说明
=============================

准备
1. 准备 Android platform-tools，把 adb.exe、AdbWinApi.dll、AdbWinUsbApi.dll 放到同一目录。
2. 安装 Python 3.8+，安装时勾选 Add to PATH。
3. 车机开启开发者选项和 USB 调试，用 USB 连接电脑。

常用命令（在本文件夹打开命令行执行）
  python carunit.py devices                 查看设备
  python carunit.py info                    查看型号/系统/分辨率
  python carunit.py top                     查看前台应用
  python carunit.py shot                    截图到 screenshots
  python carunit.py install apks            安装目录内全部 apk
  python carunit.py install app.apk --grant-permissions
  python carunit.py export com.example.app  导出 APK（含 split）
  python carunit.py logcat --package com.example.app --seconds 15 -o log.txt
  python carunit.py logcat --clear           清空日志后再采集
  python carunit.py crash                   导出崩溃日志
  python carunit.py setup --dry-run         预演调试设置
  python carunit.py setup                   修改设置并备份原值
  python carunit.py setup --restore         恢复备份的设置

说明
- adb.exe 与 carunit.py 同目录时会优先使用；也可用 --adb 指定路径。
- logcat 默认不清空设备日志，只有 --clear 才会清空。
- setup 备份写入 carunit-setup.backup.json，重复执行不会覆盖首次备份。
- split APK 会导出到 apks/<包名>/，包含 base.apk 和全部分片。
- unauthorized 表示需要在车机上确认 USB 调试授权。
- 部分车机禁用 exec-out，可改用 screencap 到设备后再 pull。

使用边界
仅用于调试你本人拥有或已获得设备所有者明确授权的 Android 设备（含车机）。
不包含绕过应用风控、破解、刷量或规避检测的功能。
请确认使用行为符合当地法律法规、车辆保修条款与目标应用协议。
"""


def read_version():
    text = (ROOT / "carunit.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"$', text, re.MULTILINE)
    if not match:
        raise RuntimeError("carunit.py 中缺少 __version__")
    return match.group(1)


def validate_archive(archive, version):
    readme_name = f"carunit-{version}/使用说明-GBK.txt"
    expected = [
        f"carunit-{version}/carunit.py",
        f"carunit-{version}/README.md",
        readme_name,
    ]
    with zipfile.ZipFile(archive) as handle:
        if handle.namelist() != expected:
            raise RuntimeError(f"ZIP 文件列表不正确: {handle.namelist()}")
        bad_file = handle.testzip()
        if bad_file:
            raise RuntimeError(f"ZIP CRC 校验失败: {bad_file}")
        if not handle.getinfo(readme_name).flag_bits & 0x800:
            raise RuntimeError("中文文件名缺少 UTF-8 标记")
        text = handle.read(readme_name).decode("gbk")
        if not text.startswith(f"carunit {version}"):
            raise RuntimeError("GBK 离线说明版本号不正确")


def build():
    version = read_version()
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    stage = dist / f"carunit-{version}"
    stage.mkdir(exist_ok=True)
    shutil.copyfile(ROOT / "carunit.py", stage / "carunit.py")
    shutil.copyfile(ROOT / "README.md", stage / "README.md")
    readme = GBK_README.format(version=version).replace("\n", "\r\n")
    (stage / "使用说明-GBK.txt").write_bytes(readme.encode("gbk"))

    archive = dist / f"carunit-{version}.zip"
    temp_archive = archive.with_suffix(".zip.tmp")
    with zipfile.ZipFile(temp_archive, "w") as handle:
        for name in ("carunit.py", "README.md", "使用说明-GBK.txt"):
            info = zipfile.ZipInfo(
                f"carunit-{version}/{name}", date_time=(2026, 1, 1, 0, 0, 0)
            )
            info.create_system = 3
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            handle.writestr(
                info,
                (stage / name).read_bytes(),
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )
    validate_archive(temp_archive, version)
    os.replace(temp_archive, archive)

    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum = dist / f"carunit-{version}.sha256.txt"
    checksum.write_bytes(f"{digest}  {archive.name}\n".encode("ascii"))
    print(f"version: {version}")
    print(f"archive: {archive}")
    print(f"sha256: {digest}")


if __name__ == "__main__":
    build()
