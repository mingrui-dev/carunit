#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
carunit — 车机 Android 调试小工具
=================================
纯标准库实现，Windows 控制台友好，配合 adb 使用。

只用于调试你本人拥有、或已获得明确授权的设备。
在车机上折腾 ADB 前，请先确认当地法规与车辆质保条款允许。

用法示例：
    python carunit.py devices
    python carunit.py info
    python carunit.py top
    python carunit.py shot
    python carunit.py install downloads/
    python carunit.py export com.example.app
    python carunit.py logcat --package com.example.app --seconds 15 -o log.txt
    python carunit.py crash
    python carunit.py setup
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

__version__ = "0.2.0"

# ---------------------------------------------------------------- 输出


def log(msg=""):
    """GBK 控制台下也不会因为中文/emoji 抛异常"""
    text = str(msg)
    try:
        print(text)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(text.encode(enc, "replace").decode(enc, "replace"))


def die(msg, code=1):
    log("错误: " + str(msg))
    raise SystemExit(code)


# ---------------------------------------------------------------- adb 封装


class AdbError(RuntimeError):
    pass


def find_adb(explicit=None):
    if explicit:
        return explicit
    local_name = "adb.exe" if os.name == "nt" else "adb"
    local_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), local_name)
    if os.path.isfile(local_path):
        return local_path
    return shutil.which("adb") or "adb"


class Adb:
    """对 adb 命令的一层薄封装，runner 可注入以便无设备测试"""

    def __init__(self, adb="adb", serial=None, runner=None, timeout=60):
        self.adb = adb
        self.serial = serial
        self.runner = runner or self._subprocess_runner
        self.timeout = timeout

    def _subprocess_runner(self, cmd, timeout=None, binary=False):
        try:
            proc = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=timeout or self.timeout,
            )
        except FileNotFoundError:
            raise AdbError("找不到 adb，请把 adb.exe 放到本目录或加入 PATH")
        except subprocess.TimeoutExpired:
            raise AdbError(f"adb 命令超时: {' '.join(cmd[:4])}")
        out = proc.stdout if binary else proc.stdout.decode("utf-8", "replace")
        err = proc.stderr.decode("utf-8", "replace")
        return proc.returncode, out, err

    def cmd(self, *args):
        base = [self.adb]
        if self.serial:
            base += ["-s", self.serial]
        return base + [str(a) for a in args]

    def run(self, *args, timeout=None, binary=False):
        cmd = self.cmd(*args)
        code, out, err = self.runner(cmd, timeout=timeout, binary=binary)
        if code != 0:
            raise AdbError((err or out or "").strip() or f"adb 返回码 {code}")
        return out

    def shell(self, *args, timeout=None):
        return self.run("shell", *args, timeout=timeout)


# ---------------------------------------------------------------- 纯函数解析器


_DEVICE_RE = re.compile(r"^(\S+)\s+(\S+)(?:\s+(.*))?$")


def parse_devices(text):
    """adb devices -l 的输出 -> [{serial, state, model...}]"""
    devices = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices") or line.startswith("*"):
            continue
        match = _DEVICE_RE.match(line)
        if not match:
            continue
        serial, state, rest = match.group(1), match.group(2), (match.group(3) or "")
        extra = {}
        for part in rest.split():
            if ":" in part:
                key, value = part.split(":", 1)
                extra[key] = value
        extra.update({"serial": serial, "state": state})
        devices.append(extra)
    return devices


def parse_props(text):
    """getprop 输出 -> dict，例如 [ro.product.model]: [Tiggo 5x]"""
    props = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        props[key.strip("[] ")] = value.strip(" []")
    return props


_FOCUS_RE = re.compile(r"mCurrentFocus=Window\{[0-9a-f]+ u0 ([^}\s]+)\}")
_RESUMED_RE = re.compile(r"mResumedActivity.*?u0 ([^/\s]+)/([^}\s]+)")


def parse_focus(text):
    """从 dumpsys window / dumpsys activity 输出里取当前前台应用"""
    match = _FOCUS_RE.search(text)
    if match:
        token = match.group(1)
        if "/" in token:
            pkg, act = token.split("/", 1)
            return {"package": pkg, "activity": act}
        return {"package": token, "activity": None}
    match = _RESUMED_RE.search(text)
    if match:
        return {"package": match.group(1), "activity": match.group(2)}
    return None


def parse_install(text):
    """adb install 输出 -> {ok, message}"""
    message = (text or "").strip()
    ok = message.startswith("Success")
    return {"ok": ok, "message": message}


def parse_pm_paths(text):
    """pm path <包名> 输出 -> 设备上的 base/split APK 路径列表"""
    paths = []
    for line in (text or "").splitlines():
        line = line.strip()
        if line.startswith("package:"):
            path = line[len("package:"):].strip()
            if path:
                paths.append(path)
    return paths


_PACKAGE_RE = re.compile(r"^[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+$")


def is_png(data):
    return isinstance(data, (bytes, bytearray)) and bytes(data[:8]) == b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------- 子命令


def cmd_devices(adb, args):
    rows = parse_devices(adb.run("devices", "-l"))
    if not rows:
        log("没有检测到设备。USB 连好车机后重试（或在车机开发者选项里确认 USB 调试已打开）。")
        return 1
    log(f"{'SERIAL':<24}{'STATE':<12}MODEL")
    for row in rows:
        log(f"{row['serial']:<24}{row['state']:<12}{row.get('model', '')}")
    return 0


def cmd_info(adb, args):
    props = parse_props(adb.shell("getprop"))
    size = adb.shell("wm", "size").strip().splitlines()
    density = adb.shell("wm", "density").strip().splitlines()
    rows = [
        ("型号", props.get("ro.product.model", "?")),
        ("厂商", props.get("ro.product.manufacturer", "?")),
        ("Android", props.get("ro.build.version.release", "?")),
        ("SDK", props.get("ro.build.version.sdk", "?")),
        ("构建号", props.get("ro.build.display.id", "?")),
        ("分辨率", size[-1] if size else "?"),
        ("密度", density[-1] if density else "?"),
    ]
    width = max(len(k) for k, _ in rows)
    for key, value in rows:
        log(f"{key:<{width}}  {value}")
    return 0


def cmd_top(adb, args):
    for probe in (("dumpsys", "window"), ("dumpsys", "activity", "activities")):
        try:
            out = adb.shell(*probe, timeout=20)
        except AdbError:
            continue
        info = parse_focus(out)
        if info:
            log(f"包名: {info['package']}")
            if info.get("activity"):
                log(f"Activity: {info['activity']}")
            return 0
    log("没解析到前台应用。可在车机上切到目标页面后重试。")
    return 1


def cmd_shot(adb, args):
    outdir = os.path.abspath(args.outdir)
    os.makedirs(outdir, exist_ok=True)
    data = adb.run("exec-out", "screencap", "-p", binary=True, timeout=30)
    if not is_png(data):
        die("截屏数据不是 PNG（部分车机需要先 `adb root` 或改用 `screencap -p /sdcard/x.png` + pull）")
    dest = os.path.join(outdir, time.strftime("shot-%Y%m%d-%H%M%S.png"))
    with open(dest, "wb") as handle:
        handle.write(data)
    log(f"已保存 {dest}（{len(data)} 字节）")
    return 0


def _collect_apks(paths):
    apks = []
    for path in paths:
        if os.path.isdir(path):
            apks += sorted(
                os.path.join(path, name)
                for name in os.listdir(path)
                if name.lower().endswith(".apk")
            )
        elif os.path.isfile(path):
            apks.append(path)
        else:
            die(f"路径不存在: {path}")
    return apks


def cmd_install(adb, args):
    apks = _collect_apks(args.paths)
    if not apks:
        die("没有找到 .apk 文件")
    failed = 0
    install_args = ["install", "-r"]
    if args.grant_permissions:
        install_args.append("-g")
    for apk in apks:
        log(f"安装 {os.path.basename(apk)} ...")
        try:
            result = parse_install(adb.run(*install_args, apk, timeout=args.timeout))
        except AdbError as exc:
            log("  失败: " + str(exc).splitlines()[0][:200])
            failed += 1
            continue
        if result["ok"]:
            log("  成功")
        else:
            log("  失败: " + result["message"].splitlines()[0][:200])
            failed += 1
    log(f"完成：{len(apks) - failed} 成功 / {failed} 失败")
    return 1 if failed else 0


def cmd_export(adb, args):
    if not _PACKAGE_RE.fullmatch(args.package):
        die(f"包名格式不正确: {args.package}")
    outdir = os.path.abspath(args.outdir)
    os.makedirs(outdir, exist_ok=True)
    remotes = parse_pm_paths(adb.shell("pm", "path", args.package))
    if not remotes:
        die(f"没有找到已安装的包: {args.package}（先 `carunit.py top` 确认包名）")
    if len(remotes) == 1:
        dests = [os.path.join(outdir, f"{args.package}.apk")]
    else:
        package_dir = os.path.join(outdir, args.package)
        os.makedirs(package_dir, exist_ok=True)
        dests = [os.path.join(package_dir, os.path.basename(remote)) for remote in remotes]
    for remote, dest in zip(remotes, dests):
        adb.run("pull", remote, dest, timeout=180)
        if not os.path.isfile(dest):
            die(f"导出失败：本地没有生成文件 {dest}")
        log(f"已导出 {dest}（{os.path.getsize(dest)} 字节）")
    if len(remotes) > 1:
        log(f"共导出 {len(remotes)} 个 APK（base + split）")
    return 0


def cmd_logcat(adb, args):
    pattern = None
    if args.grep:
        try:
            pattern = re.compile(args.grep, re.I)
        except re.error as exc:
            die(f"--grep 正则无效: {exc}")
    target = ["logcat", "-v", "time"]
    if args.package:
        pid = adb.shell("pidof", args.package).strip().split()
        if not pid:
            die(f"{args.package} 当前不在运行（pidof 为空），先启动应用再抓")
        target += ["--pid", pid[0]]
        log(f"跟踪 {args.package} (pid {pid[0]})，采集 {args.seconds} 秒 ...")
    else:
        log(f"采集全部日志 {args.seconds} 秒 ...")
    if args.clear:
        adb.run("logcat", "-c")
        log("已清空设备日志缓冲区")
    time.sleep(args.seconds)
    lines = adb.run(*(target + ["-d"]), timeout=60).splitlines()
    if pattern:
        lines = [line for line in lines if pattern.search(line)]
    text = "\n".join(lines)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text)
        log(f"已保存 {args.out}（{len(lines)} 行）")
    else:
        log(text)
    return 0


def cmd_crash(adb, args):
    data = adb.run("logcat", "-d", "-b", "crash", "-v", "time", timeout=60)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(data)
        log(f"已保存崩溃日志 {args.out}（{len(data.splitlines())} 行）")
    else:
        log(data or "(崩溃缓冲区为空)")
    return 0


_DEBUG_SETTINGS = [
    ("关闭窗口动画", "global", "window_animation_scale", "0", None),
    ("关闭过渡动画", "global", "transition_animation_scale", "0", None),
    ("关闭动画时长缩放", "global", "animator_duration_scale", "0", None),
    ("充电时常亮", "global", "stay_on_while_plugged_in", "true", ("svc", "power", "stayon", "true")),
    ("屏幕超时 30 分钟", "system", "screen_off_timeout", "1800000", None),
]


def _setting_key(setting):
    return f"{setting[1]}/{setting[2]}"


def _load_setup_state(path):
    if not os.path.exists(path):
        return {"version": 1, "values": {}}
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise AdbError(f"无法读取设置备份 {path}: {exc}")
    if not isinstance(data, dict) or not isinstance(data.get("values"), dict):
        raise AdbError(f"设置备份格式不正确: {path}")
    return data


def _save_setup_state(path, state):
    temp_path = path + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_path, path)
    except OSError as exc:
        raise AdbError(f"无法保存设置备份 {path}: {exc}")


def _write_setting(adb, setting, value):
    label, namespace, key, desired, custom_write = setting
    if custom_write and str(value) == desired:
        adb.shell(*custom_write, timeout=20)
    else:
        adb.shell("settings", "put", namespace, key, str(value), timeout=20)


def cmd_setup(adb, args):
    state_path = os.path.abspath(args.state_file)
    state = _load_setup_state(state_path)
    values = state["values"]
    if args.restore:
        if not values:
            die(f"没有可恢复的设置备份: {state_path}")
        failed = 0
        for setting in _DEBUG_SETTINGS:
            key = _setting_key(setting)
            if key not in values:
                continue
            try:
                _write_setting(adb, setting, values[key])
                log(f"  已恢复: {setting[0]} -> {values[key]}")
            except AdbError as exc:
                log(f"  恢复失败: {setting[0]} -> {str(exc).splitlines()[0][:120]}")
                failed += 1
        return 1 if failed else 0

    failed = 0
    state_changed = False
    for setting in _DEBUG_SETTINGS:
        label, namespace, key, desired, custom_write = setting
        state_key = _setting_key(setting)
        try:
            if state_key not in values:
                values[state_key] = adb.shell("settings", "get", namespace, key, timeout=20).strip()
                state_changed = True
            if args.dry_run:
                log(f"  [预演] {label}: {values[state_key]} -> {desired}")
                continue
            _write_setting(adb, setting, desired)
            log(f"  已设置: {label}")
        except AdbError as exc:
            log(f"  失败: {label} -> {str(exc).splitlines()[0][:120]}")
            failed += 1
    if state_changed and not args.dry_run:
        _save_setup_state(state_path, state)
        log(f"设置备份: {state_path}")
    if failed:
        log("部分设置失败通常是车机权限限制，不影响其它功能。")
    return 1 if failed else 0


def cmd_tcpip(adb, args):
    out = adb.run("tcpip", str(args.port), timeout=30)
    if str(args.port) not in out:
        die(f"切换无线调试失败: {out.strip() or 'adb 未返回端口信息'}")
    log(f"已切换无线调试端口 {args.port}，接着执行: carunit.py connect <车机IP>:{args.port}")
    return 0


def cmd_connect(adb, args):
    out = adb.run("connect", args.address, timeout=30).strip()
    lowered = out.lower()
    if not out or any(word in lowered for word in ("failed", "unable", "cannot", "error")):
        die(f"连接失败: {out or 'adb 未返回连接结果'}")
    log(out)
    return 0


# ---------------------------------------------------------------- 入口


def _port_number(value):
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("端口必须是整数")
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("端口必须在 1-65535 之间")
    return port


def build_parser():
    parser = argparse.ArgumentParser(
        prog="carunit",
        description="车机 Android 调试小工具（仅用于你拥有或已授权的设备）",
    )
    parser.add_argument("--adb", default=None, help="adb 可执行文件路径（默认先找同目录，再找 PATH）")
    parser.add_argument("--serial", default=None, help="多设备时指定序列号")
    parser.add_argument("--version", action="version", version=f"carunit {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("devices", help="列出已连接设备").set_defaults(func=cmd_devices)
    sub.add_parser("info", help="查看型号/系统/分辨率").set_defaults(func=cmd_info)
    sub.add_parser("top", help="查看当前前台应用包名").set_defaults(func=cmd_top)
    setup = sub.add_parser("setup", help="应用或恢复常用调试设置（动画/常亮/超时）")
    setup.add_argument("--restore", action="store_true", help="从备份恢复修改前的设置")
    setup.add_argument("--dry-run", action="store_true", help="只显示将要修改的设置")
    setup.add_argument("--state-file", default="carunit-setup.backup.json", help="设置备份文件路径")
    setup.set_defaults(func=cmd_setup)
    sub.add_parser("crash", help="导出崩溃缓冲区日志").set_defaults(func=cmd_crash)

    shot = sub.add_parser("shot", help="截图并保存到本地")
    shot.add_argument("outdir", nargs="?", default="screenshots", help="输出目录（默认 screenshots）")
    shot.set_defaults(func=cmd_shot)

    install = sub.add_parser("install", help="安装一个或多个 APK / 目录内全部 APK")
    install.add_argument("paths", nargs="+", help="APK 文件或目录")
    install.add_argument("--timeout", type=int, default=180, help="单个 APK 安装超时秒数")
    install.add_argument("--grant-permissions", action="store_true", help="安装时自动授予运行时权限（-g）")
    install.set_defaults(func=cmd_install)

    export = sub.add_parser("export", help="把已安装应用的 APK 拉回本地")
    export.add_argument("package", help="包名，如 com.example.app")
    export.add_argument("--outdir", default="apks", help="输出目录（默认 apks）")
    export.set_defaults(func=cmd_export)

    logcat = sub.add_parser("logcat", help="采集一段时间日志，可按包名过滤")
    logcat.add_argument("--package", help="只保留该包名进程的日志")
    logcat.add_argument("--seconds", type=int, default=10, help="采集时长秒数（默认 10）")
    logcat.add_argument("--grep", help="正则过滤，忽略大小写")
    logcat.add_argument("--clear", action="store_true", help="采集前清空设备日志缓冲区")
    logcat.add_argument("-o", "--out", help="保存到文件而不是打印")
    logcat.set_defaults(func=cmd_logcat)

    tcpip = sub.add_parser("tcpip", help="切到无线调试（需先 USB 连接）")
    tcpip.add_argument("--port", type=_port_number, default=5555)
    tcpip.set_defaults(func=cmd_tcpip)

    connect = sub.add_parser("connect", help="连接无线调试地址 IP:PORT")
    connect.add_argument("address")
    connect.set_defaults(func=cmd_connect)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    adb = Adb(adb=find_adb(args.adb), serial=args.serial)
    try:
        return args.func(adb, args) or 0
    except AdbError as exc:
        die(exc)
    except KeyboardInterrupt:
        log("已中断")
        return 130


if __name__ == "__main__":
    sys.exit(main())