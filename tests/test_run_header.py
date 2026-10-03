"""The one-file desktop installer also exposes the saved maintenance commands."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RunHeaderTests(unittest.TestCase):
    def test_embedded_installer_advertises_refresh_and_full_studio_update(self):
        with tempfile.TemporaryDirectory() as temp:
            environment = dict(os.environ, OUTPUT_DIR=temp)
            built = subprocess.run(
                ["bash", str(ROOT / "scripts/build_run.sh")], cwd=ROOT,
                env=environment, capture_output=True, text=True,
            )
            self.assertEqual(built.returncode, 0, built.stderr)
            installer = Path(temp) / "Connect-Dual-Spark-arm64.run"
            help_result = subprocess.run(
                ["bash", str(installer), "--help"], capture_output=True, text=True,
            )
            self.assertEqual(help_result.returncode, 0, help_result.stderr)
            self.assertIn("refresh", help_result.stdout)
            self.assertIn("update-unsloth", help_result.stdout)
            verified = subprocess.run(
                ["bash", str(installer), "--verify"], capture_output=True, text=True,
            )
            self.assertEqual(verified.returncode, 0, verified.stderr)


if __name__ == "__main__":
    unittest.main()
