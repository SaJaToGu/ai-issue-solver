import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import opencode_state_diagnostic as diag  # noqa: E402


class OpencodeStateDiagnosticTests(unittest.TestCase):
    def test_main_emits_human_report_by_default(self):
        report = {
            "binaries_found": [
                {
                    "source": "PATH",
                    "path": "/usr/local/bin/opencode",
                    "version": "1.15.13",
                }
            ],
            "running_serve": None,
            "opencode_bin_env": None,
        }
        with patch.object(diag, "_build_report", return_value=report):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = diag.main([])
            self.assertEqual(rc, 0)
            text = buf.getvalue()
        self.assertIn("OpenCode state diagnostic", text)
        self.assertIn("1.15.13", text)
        self.assertIn("/usr/local/bin/opencode", text)
        self.assertIn("Verdict:", text)

    def test_main_emits_json_with_flag(self):
        report = {
            "binaries_found": [],
            "running_serve": None,
            "opencode_bin_env": None,
        }
        with patch.object(diag, "_build_report", return_value=report):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = diag.main(["--json"])
            self.assertEqual(rc, 0)
            payload = json.loads(buf.getvalue())
        self.assertEqual(payload["binaries_found"], [])
        self.assertIsNone(payload["running_serve"])
        self.assertIsNone(payload["opencode_bin_env"])

    def test_version_extraction_simple_semver(self):
        text = "opencode 1.15.13\n"
        m = diag.VERSION_RE.search(text)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "1.15.13")

    def test_version_extraction_with_suffix(self):
        text = "opencode version 1.14.28-beta.1+local\n"
        m = diag.VERSION_RE.search(text)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "1.14.28-beta.1+local")

    def test_app_owner_detection(self):
        path = "/Applications/MiniMax Code.app/Contents/Resources/resources/opencode/opencode"
        self.assertEqual(
            diag._app_owner_for_binary(path),
            "/Applications/MiniMax Code.app",
        )

    def test_app_owner_detection_no_app(self):
        self.assertIsNone(diag._app_owner_for_binary("/usr/local/bin/opencode"))

    def test_opencode_bin_env_unset(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(diag._opencode_bin_env())

    def test_opencode_bin_env_set_relative(self):
        with patch.dict(
            "os.environ", {"OPENCODE_BIN": "./bin/opencode"}, clear=True
        ):
            # The actual fixture opencode binary is in scripts/, so
            # relative resolution must produce a usable path.
            result = diag._opencode_bin_env()
            self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
