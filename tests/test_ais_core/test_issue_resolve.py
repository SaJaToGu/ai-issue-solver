"""Smoke tests for ais_core.issue_resolve stub (Issue #1a).

Verifies that the stub is importable and exposes the expected public
surface. Behaviour tests will land alongside the real implementation.
"""

import unittest


class TestIssueResolveStub(unittest.TestCase):
    def test_module_importable(self) -> None:
        import ais_core.issue_resolve

        self.assertTrue(hasattr(ais_core.issue_resolve, "__all__"))

    def test_all_exports_resolve(self) -> None:
        from ais_core.issue_resolve import (
            ResolvedIssue,
            fetch_issue,
            find_open_issues,
            issue_is_ai_solvable,
        )

        self.assertTrue(callable(fetch_issue))
        self.assertTrue(callable(find_open_issues))
        self.assertTrue(callable(issue_is_ai_solvable))
        self.assertTrue(callable(ResolvedIssue))


if __name__ == "__main__":
    unittest.main()
