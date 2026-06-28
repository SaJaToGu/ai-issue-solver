"""Smoke tests for ais_core.json_contract stub (Issue #1a).

Verifies that the stub is importable and exposes the expected public
surface, including the canonical SCHEMA_VERSION constant. Real
envelope shape validation will land in Issue #1c.
"""

import unittest


class TestJsonContractStub(unittest.TestCase):
    def test_module_importable(self) -> None:
        import ais_core.json_contract

        self.assertTrue(hasattr(ais_core.json_contract, "__all__"))

    def test_schema_version_constant(self) -> None:
        from ais_core.json_contract import SCHEMA_VERSION

        self.assertEqual(SCHEMA_VERSION, "1.0")

    def test_all_exports_resolve(self) -> None:
        from ais_core.json_contract import (
            error_envelope,
            success_envelope,
            validate_envelope,
        )

        self.assertTrue(callable(success_envelope))
        self.assertTrue(callable(error_envelope))
        self.assertTrue(callable(validate_envelope))


if __name__ == "__main__":
    unittest.main()