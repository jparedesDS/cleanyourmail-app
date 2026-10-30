from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cleanyourmail_app import cli

FAKE = """\
import json, sys
cmd = sys.argv[1] if len(sys.argv) > 1 else ""
print(json.dumps({"ok": True, "command": cmd, "args": sys.argv[2:]}))
"""


class CliTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.script = self.root / "tools" / "mail.py"
        self.script.parent.mkdir(parents=True)
        self.script.write_text(FAKE, encoding="utf-8")
        self.config = self.root / "cleanyourmail.toml"
        self.config.write_text("# test\n", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_find_cli_explicit_file_and_directory(self):
        self.assertEqual(cli.find_cli(str(self.script)), self.script.resolve())
        self.assertEqual(cli.find_cli(str(self.root)), self.script.resolve())

    def test_run_parses_json_and_passes_arguments(self):
        result = cli.run(
            ["validate"],
            cli_path=self.script,
            config_path=self.config,
            timeout=10,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["command"], "validate")
        self.assertIn("--config", result["data"]["args"])
        self.assertIn("--json", result["data"]["args"])

    def test_missing_config_is_refused(self):
        with self.assertRaises(cli.CliError):
            cli.run(
                ["validate"],
                cli_path=self.script,
                config_path=self.root / "missing.toml",
            )

    def test_init_can_run_without_an_existing_config(self):
        result = cli.run(
            ["init", "--email", "you@example.com"],
            cli_path=self.script,
            config_path=self.root / "missing.toml",
            require_config=False,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["command"], "init")


if __name__ == "__main__":
    unittest.main()
