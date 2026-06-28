"""Smoke tests for ais_core.repo_resolve stub (Issue #1a).

These tests verify only that the stub can be imported and exposes the
expected public surface. Behaviour tests are intentionally deferred to
Issue #1b, where the real repo-resolution logic lands.
"""

import unittest


class TestRepoResolveStub(unittest.TestCase):
    def test_module_importable(self) -> None:
        import ais_core.repo_resolve

        self.assertTrue(hasattr(ais_core.repo_resolve, "__all__"))

    def test_all_exports_resolve(self) -> None:
        from ais_core.repo_resolve import (
            ResolvedRepo,
            resolve_from_git_remote,
            resolve_from_owner_repo,
            resolve_repo_hint,
        )

        self.assertTrue(callable(resolve_repo_hint))
        self.assertTrue(callable(resolve_from_owner_repo))
        self.assertTrue(callable(resolve_from_git_remote))
        self.assertTrue(callable(ResolvedRepo))


if __name__ == "__main__":
    unittest.main()
