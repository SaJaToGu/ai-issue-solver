"""Smoke tests for ais_core.secret_filter stub (Issue #1a).

Verifies that the stub is importable and exposes the expected public
surface. Behaviour tests (real pattern coverage) will land in Issue #1d.
"""

import unittest


class TestSecretFilterStub(unittest.TestCase):
    def test_module_importable(self) -> None:
        import ais_core.secret_filter

        self.assertTrue(hasattr(ais_core.secret_filter, "__all__"))

    def test_all_exports_resolve(self) -> None:
        from ais_core.secret_filter import (
            SECRED_PATTERNS,
            redact_dict,
            redact_list,
            redact_secrets,
        )

        self.assertTrue(callable(redact_secrets))
        self.assertTrue(callable(redact_dict))
        self.assertTrue(callable(redact_list))
        self.assertIsInstance(SECRED_PATTERNS, list)


if __name__ == "__main__":
    unittest.main()