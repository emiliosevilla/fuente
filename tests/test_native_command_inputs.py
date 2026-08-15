"""Security contracts for native selectors and application commands."""

import ast
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fuente.control_console import FuenteConsoleBackend
from fuente.core import app_checker


MALICIOUS_INPUT = 'Title " \\ \n") & do shell script "touch /tmp/pwned" & ("'
REPOSITORY_ROOT = Path(__file__).resolve().parent.parent


class TestNativeCommandInputs(unittest.TestCase):
    def test_macos_folder_title_is_passed_as_osascript_data(self):
        result = MagicMock(returncode=0, stdout="/tmp/chosen\n")

        with patch.object(sys, "platform", "darwin"), patch(
            "fuente.control_console.subprocess.run", return_value=result
        ) as run:
            folder = FuenteConsoleBackend.select_folder(object(), MALICIOUS_INPUT)

        self.assertEqual(folder, "/tmp/chosen")
        command = run.call_args.args[0]
        self.assertIsInstance(command, list)
        self.assertEqual(command[:2], ["osascript", "-e"])
        self.assertEqual(command[-2:], ["--", MALICIOUS_INPUT])
        self.assertNotIn(MALICIOUS_INPUT, "\n".join(command[:-2]))
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_macos_app_name_is_passed_as_osascript_data(self):
        with patch.object(sys, "platform", "darwin"), patch(
            "fuente.core.app_checker.subprocess.run"
        ) as run, patch("fuente.core.app_checker.time.sleep"):
            app_checker.close_user_apps([MALICIOUS_INPUT])

        command = run.call_args.args[0]
        self.assertIsInstance(command, list)
        self.assertEqual(command[:2], ["osascript", "-e"])
        self.assertEqual(command[-2:], ["--", MALICIOUS_INPUT])
        self.assertNotIn(MALICIOUS_INPUT, "\n".join(command[:-2]))
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_production_code_does_not_enable_shell_execution(self):
        violations = []
        for source_path in (REPOSITORY_ROOT / "fuente").rglob("*.py"):
            tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
            for call in ast.walk(tree):
                if isinstance(call, ast.Call) and any(
                    keyword.arg == "shell"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                    for keyword in call.keywords
                ):
                    violations.append(source_path.relative_to(REPOSITORY_ROOT).as_posix())

        self.assertEqual(violations, [])
