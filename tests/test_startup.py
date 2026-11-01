import tempfile
import unittest
from pathlib import Path

from nightfall.startup import (
    MIN_DOTNET_RELEASE,
    MIN_RUNTIME_DLL_BYTES,
    diagnose_startup,
    dotnet_version_name,
    ensure_environment,
    environment_summary,
    report_startup_failure,
    write_startup_log,
)
import nightfall.startup as startup


class DotnetVersionNameTests(unittest.TestCase):
    def test_known_releases(self):
        self.assertEqual(dotnet_version_name(533320), "4.8.1")
        self.assertEqual(dotnet_version_name(528040), "4.8")
        self.assertEqual(dotnet_version_name(528372), "4.8")
        self.assertEqual(dotnet_version_name(461808), "4.7.2")
        self.assertEqual(dotnet_version_name(394802), "4.6.2")

    def test_unknown_release(self):
        self.assertIsNone(dotnet_version_name(None))
        self.assertEqual(dotnet_version_name(378389), "4.5 或更低")


class DiagnoseStartupTests(unittest.TestCase):
    def _dll(self, directory, size):
        path = Path(directory) / "Python.Runtime.dll"
        path.write_bytes(b"\0" * size)
        return path

    def test_missing_dotnet_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            problems = diagnose_startup(
                release=None,
                runtime_dll=self._dll(tmp, MIN_RUNTIME_DLL_BYTES),
                is_frozen=True,
            )
        self.assertTrue(any(".NET Framework" in item for item in problems))

    def test_old_dotnet_reported_with_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            problems = diagnose_startup(
                release=394802,
                runtime_dll=self._dll(tmp, MIN_RUNTIME_DLL_BYTES),
                is_frozen=True,
            )
        self.assertEqual(len(problems), 1)
        self.assertIn("4.6.2", problems[0])
        self.assertIn("4.7.2", problems[0])

    def test_minimum_release_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            problems = diagnose_startup(
                release=MIN_DOTNET_RELEASE,
                runtime_dll=self._dll(tmp, MIN_RUNTIME_DLL_BYTES),
                is_frozen=True,
            )
        self.assertEqual(problems, [])

    def test_missing_dll_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            problems = diagnose_startup(
                release=528040,
                runtime_dll=Path(tmp) / "Python.Runtime.dll",
                is_frozen=True,
            )
        self.assertEqual(len(problems), 1)
        self.assertIn("完整解压", problems[0])

    def test_truncated_dll_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            problems = diagnose_startup(
                release=528040,
                runtime_dll=self._dll(tmp, 1024),
                is_frozen=True,
            )
        self.assertEqual(len(problems), 1)
        self.assertIn("1024 字节", problems[0])

    def test_dll_check_skipped_when_running_from_source(self):
        problems = diagnose_startup(
            release=528040,
            runtime_dll=Path("nowhere") / "Python.Runtime.dll",
            is_frozen=False,
        )
        self.assertEqual(problems, [])


class StartupLogTests(unittest.TestCase):
    def test_log_written_to_given_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_startup_log("traceback", log_dir=tmp)
            self.assertIsNotNone(path)
            self.assertEqual(path.read_text(encoding="utf-8"), "traceback")

    def test_environment_summary_reports_release_and_dll_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            dll = Path(tmp) / "Python.Runtime.dll"
            dll.write_bytes(b"\0" * 2048)
            summary = environment_summary(release=528040, runtime_dll=dll)
        self.assertIn("4.8", summary)
        self.assertIn("2048 字节", summary)

    def test_environment_summary_handles_missing_items(self):
        summary = environment_summary(
            release=None,
            runtime_dll=Path("nowhere") / "Python.Runtime.dll",
        )
        self.assertIn("未检测到 .NET Framework", summary)
        self.assertIn("不存在", summary)


class ReportMessageTests(unittest.TestCase):
    def setUp(self):
        self.shown = []
        self.opened = []
        self._ask = startup._ask
        self._open_path = startup._open_path
        startup._open_path = lambda target: self.opened.append(target) or True

    def tearDown(self):
        startup._ask = self._ask
        startup._open_path = self._open_path

    def _answer(self, yes):
        startup._ask = lambda text, title: self.shown.append((text, title)) or yes

    def test_dotnet_problem_opens_download_page(self):
        self._answer(True)
        with tempfile.TemporaryDirectory() as tmp:
            text = report_startup_failure(
                error=RuntimeError("Failed to resolve Python.Runtime.Loader.Initialize"),
                problems=["没有检测到 .NET Framework 4.x。"],
                log_dir=tmp,
            )
            written = (Path(tmp) / "startup-error.log").read_text(encoding="utf-8")
        message, title = self.shown[0]
        self.assertIn("原因", message)
        self.assertIn(startup.DOTNET_URL, message)
        self.assertIn("启动失败", title)
        self.assertEqual(self.opened, [startup.DOTNET_URL])
        self.assertIn("RuntimeError", text)
        self.assertIn("Failed to resolve", written)

    def test_unknown_cause_opens_log_file(self):
        self._answer(True)
        with tempfile.TemporaryDirectory() as tmp:
            report_startup_failure(
                error=RuntimeError("boom"),
                problems=[],
                log_dir=tmp,
            )
        self.assertEqual(str(self.opened[0]), str(Path(tmp) / "startup-error.log"))
        self.assertIn("截图发给开发者", self.shown[0][0])

    def test_declining_opens_nothing(self):
        self._answer(False)
        with tempfile.TemporaryDirectory() as tmp:
            report_startup_failure(error=RuntimeError("boom"), problems=[], log_dir=tmp)
        self.assertEqual(self.opened, [])

    def test_dll_problem_opens_program_folder(self):
        self._answer(True)
        program_dir = Path("C:/Program/Nightfall")
        self._program_dir = startup._program_dir
        startup._program_dir = lambda: program_dir
        try:
            with tempfile.TemporaryDirectory() as tmp:
                report_startup_failure(
                    error=RuntimeError("boom"),
                    problems=[
                        "程序目录里找不到 Python.Runtime.dll。请把 ZIP 完整解压后运行，"
                    ],
                    log_dir=tmp,
                )
        finally:
            startup._program_dir = self._program_dir
        self.assertEqual(self.opened, [program_dir])
        self.assertIn("覆盖到程序文件夹", self.shown[0][0])

    def test_runtime_crash_uses_different_wording(self):
        self._answer(False)
        with tempfile.TemporaryDirectory() as tmp:
            report_startup_failure(
                error=ValueError("bad payload"),
                problems=[],
                log_dir=tmp,
                during_startup=False,
            )
        message, title = self.shown[0]
        self.assertIn("程序遇到错误", message)
        self.assertNotIn("启动失败", title)
        self.assertIn("ValueError: bad payload", message)


class EnsureEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self._report = startup.report_startup_failure
        self._diag = startup.diagnose_startup
        startup.report_startup_failure = (
            lambda error=None, problems=None, log_dir=None, during_startup=True:
            self.calls.append(problems) or ""
        )

    def tearDown(self):
        startup.report_startup_failure = self._report
        startup.diagnose_startup = self._diag

    def test_passes_when_nothing_wrong(self):
        startup.diagnose_startup = lambda: []
        self.assertTrue(ensure_environment())
        self.assertEqual(self.calls, [])

    def test_reports_and_stops_when_problems_found(self):
        startup.diagnose_startup = lambda: ["没有检测到 .NET Framework 4.x。"]
        self.assertFalse(ensure_environment())
        self.assertEqual(self.calls, [["没有检测到 .NET Framework 4.x。"]])


if __name__ == "__main__":
    unittest.main()
