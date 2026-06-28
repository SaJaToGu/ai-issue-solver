"""Tests for ais_core.json_contract (Issue #1c).

Covers both the success/error envelope shape contracts and the
``validate_envelope`` strict-mode validator.
"""

import unittest

from ais_core.json_contract import (
    SCHEMA_VERSION,
    error_envelope,
    success_envelope,
    validate_envelope,
)


class TestSchemaVersionConstant(unittest.TestCase):
    def test_schema_version_is_one_point_zero(self) -> None:
        self.assertEqual(SCHEMA_VERSION, "1.0")


class TestSuccessEnvelope(unittest.TestCase):
    def test_minimal_shape(self) -> None:
        e = success_envelope("solve-issue", {"pr_url": "https://x"})
        self.assertEqual(e["schema_version"], SCHEMA_VERSION)
        self.assertTrue(e["ok"])
        self.assertEqual(e["command"], "solve-issue")
        self.assertEqual(e["data"], {"pr_url": "https://x"})
        self.assertEqual(e["warnings"], [])
        self.assertNotIn("elapsed_ms", e)

    def test_warnings_default_empty_list(self) -> None:
        e = success_envelope("c", {})
        self.assertEqual(e["warnings"], [])
        self.assertIsInstance(e["warnings"], list)

    def test_with_warnings(self) -> None:
        e = success_envelope("c", {}, warnings=["w1", "w2"])
        self.assertEqual(e["warnings"], ["w1", "w2"])

    def test_with_elapsed_ms(self) -> None:
        e = success_envelope("c", {}, elapsed_ms=123)
        self.assertEqual(e["elapsed_ms"], 123)

    def test_data_can_be_any_json(self) -> None:
        e = success_envelope("c", [1, 2, 3])
        self.assertEqual(e["data"], [1, 2, 3])
        e2 = success_envelope("c", "scalar")
        self.assertEqual(e2["data"], "scalar")
        e3 = success_envelope("c", None)
        self.assertIsNone(e3["data"])


class TestErrorEnvelope(unittest.TestCase):
    def test_minimal_shape(self) -> None:
        e = error_envelope("solve-issue", "issue_not_found", "Issue #123 not found")
        self.assertEqual(e["schema_version"], SCHEMA_VERSION)
        self.assertFalse(e["ok"])
        self.assertEqual(e["command"], "solve-issue")
        self.assertEqual(e["error"]["code"], "issue_not_found")
        self.assertEqual(e["error"]["message"], "Issue #123 not found")
        self.assertNotIn("hint", e["error"])
        self.assertNotIn("elapsed_ms", e)

    def test_with_hint(self) -> None:
        e = error_envelope("c", "code", "msg", hint="try this")
        self.assertEqual(e["error"]["hint"], "try this")

    def test_with_elapsed_ms(self) -> None:
        e = error_envelope("c", "code", "msg", elapsed_ms=42)
        self.assertEqual(e["elapsed_ms"], 42)

    def test_error_body_keys(self) -> None:
        e = error_envelope("c", "code", "msg", hint="h")
        self.assertEqual(set(e["error"].keys()), {"code", "message", "hint"})


class TestValidateEnvelope(unittest.TestCase):
    def test_accepts_valid_success(self) -> None:
        validate_envelope(success_envelope("c", {}))

    def test_accepts_valid_error(self) -> None:
        validate_envelope(error_envelope("c", "code", "msg"))

    def test_rejects_non_dict(self) -> None:
        with self.assertRaises(ValueError):
            validate_envelope("not a dict")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            validate_envelope([1, 2, 3])  # type: ignore[arg-type]

    def test_rejects_wrong_schema_version(self) -> None:
        with self.assertRaises(ValueError):
            validate_envelope(
                {
                    "schema_version": "2.0",
                    "ok": True,
                    "command": "c",
                    "data": {},
                }
            )

    def test_rejects_missing_ok(self) -> None:
        with self.assertRaises(ValueError):
            validate_envelope({"schema_version": SCHEMA_VERSION, "command": "c"})

    def test_rejects_non_bool_ok(self) -> None:
        with self.assertRaises(ValueError):
            validate_envelope(
                {
                    "schema_version": SCHEMA_VERSION,
                    "ok": "yes",
                    "command": "c",
                    "data": {},
                }
            )

    def test_rejects_success_without_data(self) -> None:
        with self.assertRaises(ValueError):
            validate_envelope(
                {"schema_version": SCHEMA_VERSION, "ok": True, "command": "c"}
            )

    def test_rejects_error_without_error_field(self) -> None:
        with self.assertRaises(ValueError):
            validate_envelope(
                {"schema_version": SCHEMA_VERSION, "ok": False, "command": "c"}
            )

    def test_rejects_error_without_code(self) -> None:
        with self.assertRaises(ValueError):
            validate_envelope(
                {
                    "schema_version": SCHEMA_VERSION,
                    "ok": False,
                    "command": "c",
                    "error": {"message": "x"},
                }
            )

    def test_rejects_error_without_message(self) -> None:
        with self.assertRaises(ValueError):
            validate_envelope(
                {
                    "schema_version": SCHEMA_VERSION,
                    "ok": False,
                    "command": "c",
                    "error": {"code": "x"},
                }
            )

    def test_rejects_non_dict_error(self) -> None:
        with self.assertRaises(ValueError):
            validate_envelope(
                {
                    "schema_version": SCHEMA_VERSION,
                    "ok": False,
                    "command": "c",
                    "error": "string",
                }
            )


if __name__ == "__main__":
    unittest.main()
