#!/usr/bin/env python3
"""
Tests für die erweiterten Codex Sandbox-Funktionen (--add-dir, --sandbox-mode, Preflight-Checks).
"""

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from solve_issues import (
    build_codex_command,
    preflight_temp_dir_check,
    validate_worker_changes,
)


class CodexSandboxTests(unittest.TestCase):
    def test_build_codex_command_includes_additional_dirs_and_sandbox_mode(self):
        with patch("solve_issues.find_codex_executable", return_value="/usr/bin/codex"):
            cmd = build_codex_command(
                "Fix issue",
                "/tmp/repo",
                additional_dirs=["/tmp/cache", "/tmp/workspace"],
                sandbox_mode="trusted-automation",
            )
        self.assertIn("--add-dir", cmd)
        self.assertIn("/tmp/cache", cmd)
        self.assertIn("/tmp/workspace", cmd)
        self.assertIn("--sandbox", cmd)
        self.assertIn("trusted-automation", cmd)

    def test_build_codex_command_defaults_to_workspace_write_sandbox(self):
        with patch("solve_issues.find_codex_executable", return_value="/usr/bin/codex"):
            cmd = build_codex_command("Fix issue", "/tmp/repo")
        self.assertIn("--sandbox", cmd)
        self.assertIn("workspace-write", cmd)

    def test_preflight_temp_dir_check_creates_workspace_temp_if_not_writable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Simuliere nicht beschreibbares Verzeichnis
            os.chmod(tmpdir, 0o555)  # Nur Lesen/Execute
            printed = io.StringIO()
            with contextlib.redirect_stdout(printed):
                additional_dirs = preflight_temp_dir_check(tmpdir)
            # Erwarte entweder ein workspace-temp (falls möglich) oder ein Fallback-Verzeichnis
            self.assertEqual(len(additional_dirs), 1)
            self.assertTrue(additional_dirs[0].endswith("workspace-temp") or "/tmp/ai-issue-solver-workspace" in additional_dirs[0])

    def test_preflight_temp_dir_check_returns_empty_if_writable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            additional_dirs = preflight_temp_dir_check(tmpdir)
            self.assertEqual(len(additional_dirs), 0)

    def test_validate_worker_changes_detects_write_permission_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            readme = Path(tmpdir) / "README.md"
            readme.write_text("test", encoding="utf-8")
            os.chmod(readme, 0o444)  # Nur Lesen

            validation = validate_worker_changes(tmpdir, " M README.md\n")
            self.assertFalse(validation.ok)
            self.assertIn("Keine Schreibrechte", validation.errors[0])

    def test_validate_worker_changes_detects_missing_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            validation = validate_worker_changes(tmpdir, " M missing.py\n")
            self.assertFalse(validation.ok)
            self.assertIn("Datei konnte nicht erstellt werden", validation.errors[0])


if __name__ == "__main__":
    unittest.main()