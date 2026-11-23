import subprocess
import sys
import unittest
from pathlib import Path


LAB_ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def test_launcher_help_is_available_without_starting_network(self):
        result = subprocess.run(
            [sys.executable, str(LAB_ROOT / "run_chat.py"), "--help"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Serverless UDP chat", result.stdout)
        self.assertIn("name", result.stdout)
        self.assertIn("passphrase", result.stdout)


if __name__ == "__main__":
    unittest.main()
