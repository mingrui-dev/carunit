# -*- coding: utf-8 -*-
"""carunit 单元测试：全部基于假 adb，无需真机。"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import carunit


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


class FakeRunner:
    """按命令片段返回预设结果，并记录调用顺序"""

    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or {}

    def __call__(self, cmd, timeout=None, binary=False):
        self.calls.append(list(cmd))
        joined = " ".join(cmd)
        for fragment, value in self.responses.items():
            if fragment in joined:
                if callable(value):
                    return value(cmd)
                return value
        return (0, b"" if binary else "", "")


def make_adb(runner):
    return carunit.Adb(runner=runner)


def setup_args(state_file, restore=False, dry_run=False):
    return carunit.argparse.Namespace(
        state_file=str(state_file), restore=restore, dry_run=dry_run
    )


class TestParsers(unittest.TestCase):
    def test_parse_devices_with_metadata(self):
        text = (
            "List of devices attached\n"
            "0123456789ABCDEF\tdevice product:tiggo model:Tiggo_5x device:tiggo\n"
            "192.168.1.9:5555\tunauthorized\n"
        )
        rows = carunit.parse_devices(text)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["serial"], "0123456789ABCDEF")
        self.assertEqual(rows[0]["state"], "device")
        self.assertEqual(rows[0]["model"], "Tiggo_5x")
        self.assertEqual(rows[1]["state"], "unauthorized")

    def test_parse_props_strips_brackets(self):
        text = "[ro.product.model]: [Tiggo 5x]\n[ro.build.version.sdk]: [30]\n"
        props = carunit.parse_props(text)
        self.assertEqual(props["ro.product.model"], "Tiggo 5x")
        self.assertEqual(props["ro.build.version.sdk"], "30")

    def test_parse_focus_window_form(self):
        text = "  mCurrentFocus=Window{1a2b3c u0 com.example.music/com.example.ui.MainActivity}"
        info = carunit.parse_focus(text)
        self.assertEqual(info["package"], "com.example.music")
        self.assertEqual(info["activity"], "com.example.ui.MainActivity")

    def test_parse_focus_resumed_activity_fallback(self):
        text = "mResumedActivity: ActivityRecord{abc u0 com.android.settings/.Settings t42}"
        info = carunit.parse_focus(text)
        self.assertEqual(info["package"], "com.android.settings")
        self.assertEqual(info["activity"], ".Settings")

    def test_parse_focus_returns_none_for_noise(self):
        self.assertIsNone(carunit.parse_focus("mCurrentFocus=null"))

    def test_parse_install_success_and_failure(self):
        self.assertTrue(carunit.parse_install("Success\n")["ok"])
        failed = carunit.parse_install("Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE]")
        self.assertFalse(failed["ok"])
        self.assertIn("INSTALL_FAILED", failed["message"])

    def test_parse_pm_paths_returns_base_and_splits(self):
        text = (
            "package:/data/app/com.x-1/base.apk\n"
            "package:/data/app/com.x-1/split_config.arm64_v8a.apk\n"
        )
        self.assertEqual(
            carunit.parse_pm_paths(text),
            [
                "/data/app/com.x-1/base.apk",
                "/data/app/com.x-1/split_config.arm64_v8a.apk",
            ],
        )
        self.assertEqual(carunit.parse_pm_paths(""), [])


class TestAdbWrapper(unittest.TestCase):
    def test_serial_is_injected(self):
        runner = FakeRunner()
        adb = carunit.Adb(serial="DEV123", runner=runner)
        adb.run("devices")
        self.assertEqual(runner.calls[0][:3], ["adb", "-s", "DEV123"])

    def test_nonzero_exit_raises_with_stderr(self):
        adb = carunit.Adb(runner=lambda cmd, timeout=None, binary=False: (1, "", "device offline"))
        with self.assertRaises(carunit.AdbError) as ctx:
            adb.run("shell", "getprop")
        self.assertIn("device offline", str(ctx.exception))

    def test_is_png(self):
        self.assertTrue(carunit.is_png(PNG_BYTES))
        self.assertFalse(carunit.is_png(b"not-a-png"))

    def test_find_adb_prefers_explicit_path(self):
        self.assertEqual(carunit.find_adb(r"D:\platform-tools\adb.exe"), r"D:\platform-tools\adb.exe")

    def test_find_adb_uses_local_executable(self):
        with patch.object(carunit.os.path, "isfile", return_value=True), patch.object(
            carunit.shutil, "which", return_value=None
        ):
            found = carunit.find_adb()
        self.assertTrue(found.endswith("adb.exe" if os.name == "nt" else "adb"))

    def test_find_adb_falls_back_to_path(self):
        with patch.object(carunit.os.path, "isfile", return_value=False), patch.object(
            carunit.shutil, "which", return_value="/usr/bin/adb"
        ):
            self.assertEqual(carunit.find_adb(), "/usr/bin/adb")


class TestCommands(unittest.TestCase):
    def test_shot_saves_png_to_output_dir(self):
        runner = FakeRunner({"exec-out": (0, PNG_BYTES, "")})
        with tempfile.TemporaryDirectory() as tmp:
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = carunit.cmd_shot(make_adb(runner), carunit.argparse.Namespace(outdir=tmp))
            self.assertEqual(code, 0)
            files = [f for f in os.listdir(tmp) if f.endswith(".png")]
            self.assertEqual(len(files), 1)
            with open(os.path.join(tmp, files[0]), "rb") as handle:
                self.assertTrue(carunit.is_png(handle.read()))

    def test_shot_rejects_non_png(self):
        runner = FakeRunner({"exec-out": (0, b"error: no permission", "")})
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                with redirect_stdout(io.StringIO()):
                    carunit.cmd_shot(make_adb(runner), carunit.argparse.Namespace(outdir=tmp))

    def test_install_directory_counts_failures_without_granting_permissions(self):
        runner = FakeRunner(
            {
                "good.apk": (0, "Success\n", ""),
                "bad.apk": (0, "Failure [INSTALL_FAILED_INVALID_APK]\n", ""),
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("good.apk", "bad.apk"):
                Path(tmp, name).touch()
            args = carunit.argparse.Namespace(paths=[tmp], timeout=30, grant_permissions=False)
            with redirect_stdout(io.StringIO()):
                code = carunit.cmd_install(make_adb(runner), args)
            self.assertEqual(code, 1)
        install_calls = [call for call in runner.calls if "install" in call]
        self.assertTrue(install_calls)
        self.assertTrue(all("-g" not in call for call in install_calls))

    def test_install_grants_permissions_only_when_requested(self):
        runner = FakeRunner({"install": (0, "Success\n", "")})
        with tempfile.TemporaryDirectory() as tmp:
            apk = Path(tmp, "app.apk")
            apk.touch()
            args = carunit.argparse.Namespace(paths=[str(apk)], timeout=30, grant_permissions=True)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(carunit.cmd_install(make_adb(runner), args), 0)
        self.assertIn("-g", runner.calls[0])

    def test_logcat_filters_and_saves_without_clearing_by_default(self):
        log_text = "11-26 10:00:00.000 I/App(1234): hello\n11-26 10:00:01.000 E/App(1234): boom\n"
        runner = FakeRunner(
            {
                "pidof": (0, "1234\n", ""),
                "logcat -v time --pid 1234 -d": (0, log_text, ""),
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "log.txt")
            args = carunit.argparse.Namespace(
                package="com.example.app", seconds=0, grep="boom", out=out, clear=False
            )
            with redirect_stdout(io.StringIO()):
                code = carunit.cmd_logcat(make_adb(runner), args)
            self.assertEqual(code, 0)
            with open(out, encoding="utf-8") as handle:
                content = handle.read()
            self.assertIn("boom", content)
            self.assertNotIn("hello", content)
        self.assertFalse(any(call[1:3] == ["logcat", "-c"] for call in runner.calls))

    def test_logcat_clear_is_opt_in(self):
        runner = FakeRunner()
        args = carunit.argparse.Namespace(
            package=None, seconds=0, grep=None, out=None, clear=True
        )
        with redirect_stdout(io.StringIO()):
            self.assertEqual(carunit.cmd_logcat(make_adb(runner), args), 0)
        self.assertTrue(any(call[1:3] == ["logcat", "-c"] for call in runner.calls))

    def test_logcat_rejects_invalid_regex(self):
        args = carunit.argparse.Namespace(
            package=None, seconds=0, grep="[", out=None, clear=False
        )
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            carunit.cmd_logcat(make_adb(FakeRunner()), args)

    def test_logcat_bails_when_package_not_running(self):
        runner = FakeRunner({"pidof": (0, "", "")})
        args = carunit.argparse.Namespace(
            package="com.gone", seconds=0, grep=None, out=None, clear=False
        )
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            carunit.cmd_logcat(make_adb(runner), args)

    def test_export_pulls_single_apk(self):
        runner = FakeRunner({"pm path": (0, "package:/data/app/x/base.apk\n", "")})

        def fake_pull(cmd):
            with open(cmd[-1], "wb") as handle:
                handle.write(b"APKDATA")
            return (0, "", "")

        runner.responses["pull"] = fake_pull
        with tempfile.TemporaryDirectory() as tmp:
            args = carunit.argparse.Namespace(package="com.example.app", outdir=tmp)
            with redirect_stdout(io.StringIO()):
                code = carunit.cmd_export(make_adb(runner), args)
            self.assertEqual(code, 0)
            self.assertTrue(os.path.isfile(os.path.join(tmp, "com.example.app.apk")))

    def test_export_pulls_all_split_apks(self):
        runner = FakeRunner(
            {
                "pm path": (
                    0,
                    "package:/data/app/x/base.apk\n"
                    "package:/data/app/x/split_config.arm64_v8a.apk\n",
                    "",
                )
            }
        )

        def fake_pull(cmd):
            with open(cmd[-1], "wb") as handle:
                handle.write(b"APKDATA")
            return (0, "", "")

        runner.responses["pull"] = fake_pull
        with tempfile.TemporaryDirectory() as tmp:
            args = carunit.argparse.Namespace(package="com.example.app", outdir=tmp)
            with redirect_stdout(io.StringIO()):
                code = carunit.cmd_export(make_adb(runner), args)
            self.assertEqual(code, 0)
            package_dir = Path(tmp, "com.example.app")
            self.assertEqual(
                sorted(path.name for path in package_dir.iterdir()),
                ["base.apk", "split_config.arm64_v8a.apk"],
            )

    def test_export_rejects_path_traversal_package(self):
        runner = FakeRunner()
        with tempfile.TemporaryDirectory() as tmp:
            args = carunit.argparse.Namespace(package="../../escape", outdir=tmp)
            with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
                carunit.cmd_export(make_adb(runner), args)
        self.assertFalse(any("pm path" in call for call in runner.calls))

    def test_top_reads_window_focus(self):
        runner = FakeRunner(
            {"dumpsys window": (0, "mCurrentFocus=Window{aa u0 com.example.music/.Main}", "")}
        )
        with redirect_stdout(io.StringIO()) as buf:
            code = carunit.cmd_top(make_adb(runner), carunit.argparse.Namespace())
        self.assertEqual(code, 0)
        self.assertIn("com.example.music", buf.getvalue())

    def test_setup_dry_run_does_not_change_or_save(self):
        original_values = {
            "global/window_animation_scale": "1",
            "global/transition_animation_scale": "1",
            "global/animator_duration_scale": "1",
            "global/stay_on_while_plugged_in": "0",
            "system/screen_off_timeout": "60000",
        }

        def runner(cmd, timeout=None, binary=False):
            if cmd[1:4] == ["shell", "settings", "get"]:
                return 0, original_values[f"{cmd[4]}/{cmd[5]}"] + "\n", ""
            return 0, "", ""

        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp, "setup.json")
            with redirect_stdout(io.StringIO()):
                code = carunit.cmd_setup(carunit.Adb(runner=runner), setup_args(state_file, dry_run=True))
            self.assertEqual(code, 0)
            self.assertFalse(state_file.exists())

    def test_setup_backs_up_and_restores_original_values(self):
        original_values = {
            "global/window_animation_scale": "1",
            "global/transition_animation_scale": "1",
            "global/animator_duration_scale": "1",
            "global/stay_on_while_plugged_in": "0",
            "system/screen_off_timeout": "60000",
        }
        calls = []

        def runner(cmd, timeout=None, binary=False):
            calls.append(list(cmd))
            if cmd[1:4] == ["shell", "settings", "get"]:
                return 0, original_values[f"{cmd[4]}/{cmd[5]}"] + "\n", ""
            return 0, "", ""

        adb = carunit.Adb(runner=runner)
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp, "setup.json")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(carunit.cmd_setup(adb, setup_args(state_file)), 0)
            with state_file.open(encoding="utf-8") as handle:
                state = json.load(handle)
            self.assertEqual(state["values"], original_values)
            self.assertIn(
                ["adb", "shell", "svc", "power", "stayon", "true"], calls
            )
            with redirect_stdout(io.StringIO()):
                self.assertEqual(carunit.cmd_setup(adb, setup_args(state_file, restore=True)), 0)
            self.assertIn(
                ["adb", "shell", "settings", "put", "global", "window_animation_scale", "1"],
                calls,
            )
            self.assertIn(
                ["adb", "shell", "settings", "put", "global", "stay_on_while_plugged_in", "0"],
                calls,
            )

    def test_setup_reports_partial_failure(self):
        runner = FakeRunner({"animator_duration_scale": (1, "", "Permission denial")})
        with tempfile.TemporaryDirectory() as tmp:
            with redirect_stdout(io.StringIO()):
                code = carunit.cmd_setup(
                    make_adb(runner), setup_args(Path(tmp, "setup.json"))
                )
            self.assertEqual(code, 1)

    def test_connect_detects_failure(self):
        runner = FakeRunner({"connect": (0, "failed to connect to 192.168.1.9:5555", "")})
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            carunit.cmd_connect(
                make_adb(runner), carunit.argparse.Namespace(address="192.168.1.9:5555")
            )

    def test_connect_accepts_success(self):
        runner = FakeRunner({"connect": (0, "connected to 192.168.1.9:5555", "")})
        with redirect_stdout(io.StringIO()):
            code = carunit.cmd_connect(
                make_adb(runner), carunit.argparse.Namespace(address="192.168.1.9:5555")
            )
        self.assertEqual(code, 0)

    def test_tcpip_detects_missing_port(self):
        runner = FakeRunner({"tcpip": (0, "error: device offline", "")})
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            carunit.cmd_tcpip(make_adb(runner), carunit.argparse.Namespace(port=5555))


class TestParser(unittest.TestCase):
    def test_new_safety_flags_parse(self):
        args = carunit.build_parser().parse_args(
            ["install", "app.apk", "--grant-permissions"]
        )
        self.assertTrue(args.grant_permissions)
        args = carunit.build_parser().parse_args(["logcat", "--clear"])
        self.assertTrue(args.clear)
        args = carunit.build_parser().parse_args(["setup", "--restore", "--dry-run"])
        self.assertTrue(args.restore)
        self.assertTrue(args.dry_run)

    def test_invalid_port_is_rejected(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            carunit.build_parser().parse_args(["tcpip", "--port", "70000"])

    def test_parser_requires_subcommand(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                carunit.build_parser().parse_args([])


if __name__ == "__main__":
    unittest.main(verbosity=2)
