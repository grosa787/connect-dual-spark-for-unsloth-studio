from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import unittest
from unittest.mock import patch

from dual_spark.cli import main
from dual_spark.language import set_language


class CliLanguageTests(unittest.TestCase):
    def test_check_output_switches_between_english_and_russian(self):
        class FakeRunner:
            log_path = Path("/tmp/connect-dual-spark-test.log")

            def __init__(self, **kwargs):
                pass

        class FakeInstaller:
            def __init__(self, runner):
                pass

            def check(self):
                pass

        try:
            with patch("dual_spark.cli.Runner", FakeRunner), patch("dual_spark.cli.Installer", FakeInstaller):
                english = StringIO()
                with redirect_stdout(english):
                    self.assertEqual(main(["--lang", "en", "check"]), 0)
                russian = StringIO()
                with redirect_stdout(russian):
                    self.assertEqual(main(["check", "--lang", "ru"]), 0)
        finally:
            set_language("en")

        self.assertIn("Log:", english.getvalue())
        self.assertIn("routing, and SSH are ready", english.getvalue())
        self.assertIn("Журнал:", russian.getvalue())
        self.assertIn("маршрут и SSH работают", russian.getvalue())

    def test_russian_help_and_invalid_command(self):
        try:
            help_output = StringIO()
            with redirect_stdout(help_output), self.assertRaises(SystemExit) as done:
                main(["--lang", "ru", "--help"])
            self.assertEqual(done.exception.code, 0)
            self.assertIn("использование:", help_output.getvalue())
            self.assertIn("Команды", help_output.getvalue())
            self.assertIn("Параметры", help_output.getvalue())

            error_output = StringIO()
            with redirect_stderr(error_output), self.assertRaises(SystemExit) as failed:
                main(["--lang", "ru", "unknown"])
            self.assertEqual(failed.exception.code, 2)
            self.assertIn("неверное значение", error_output.getvalue())
        finally:
            set_language("en")

    def test_studio_command_uses_existing_pair_setup_when_cable_is_absent(self):
        calls = []

        class FakeRunner:
            log_path = Path("/tmp/connect-dual-spark-test.log")

            def __init__(self, **kwargs):
                pass

        class FakeInstaller:
            def __init__(self, runner):
                pass

            def verify_standalone(self):
                calls.append("verify_standalone")

            def launch_studio(self):
                calls.append("launch_studio")

            def detect_cluster(self):
                raise AssertionError("must not require a peer with no cable")

        with patch("dual_spark.cli.Runner", FakeRunner), \
             patch("dual_spark.cli.Installer", FakeInstaller), \
             patch("dual_spark.cli.connectx_cable_present", return_value=False), \
             redirect_stdout(StringIO()):
            self.assertEqual(main(["--lang", "en", "studio"]), 0)
        self.assertEqual(calls, ["verify_standalone", "launch_studio"])


if __name__ == "__main__":
    unittest.main()
