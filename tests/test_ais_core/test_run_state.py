"""Smoke tests for ais_core.run_state stub (Issue #1a).

Verifies that the stub is importable and exposes the expected public
surface. Real Run-ID generation and state persistence will land in
Issue #1c.
"""

import unittest


class TestRunStateStub(unittest.TestCase):
    def test_module_importable(self) -> None:
        import ais_core.run_state

        self.assertTrue(hasattr(ais_core.run_state, "__all__"))

    def test_all_exports_resolve(self) -> None:
        from ais_core.run_state import (
            RunState,
            load_state,
            make_run_id,
            save_state,
        )

        self.assertTrue(callable(make_run_id))
        self.assertTrue(callable(save_state))
        self.assertTrue(callable(load_state))
        self.assertTrue(callable(RunState))


if __name__ == "__main__":
    unittest.main()
