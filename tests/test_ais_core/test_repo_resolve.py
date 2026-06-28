"""Tests for ais_core.repo_resolve (Issue #1b).

Coverage:
- Unit tests for resolve_from_owner_repo, resolve_from_git_remote,
  resolve_repo_hint (no network access, all tests offline).
- Characterization tests for the legacy behaviour: owner comes from
  config/auth, ``args.repo`` is the repo-name string. Captured as a
  test helper ``_legacy_resolve()`` — NOT exposed as a production
  function in ais_core.
- Comparison tests: library and legacy agree on the simple
  ``(owner, repo)`` case.
- No-network test: monkey-patch subprocess to ensure resolve_from_git_remote
  does not call any URL beyond the local git binary.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ais_core.repo_resolve import (
    ResolvedRepo,
    resolve_from_owner_repo,
    resolve_from_git_remote,
    resolve_repo_hint,
)


# --- Test-Helper: characterizes pre-#470 behaviour -----------------------------
# This is NOT a production function. It exists only to pin down what
# the old solve_issues.py code path *would* do, so that we can verify
# the new library function produces an equivalent result.

def _legacy_resolve(owner: str, repo: str) -> ResolvedRepo:
    """Characterization of the pre-#470 behaviour.

    Pre-#470, scripts/solve_issues.py accepted ``--repo <name>`` plus
    an ``owner`` derived from preflight_checks / require_github_config
    (i.e. from the GitHub auth response). There was no unified
    ``ResolvedRepo`` shape; the script just used the two strings
    independently.

    This helper pins the equivalent of that code path: take
    ``(owner, repo)`` strings, return a ResolvedRepo with the
    canonical remote URL and no local path. This is the behaviour we
    want to preserve across the refactor.
    """
    return ResolvedRepo(
        owner=owner,
        repo=repo,
        remote=f"https://github.com/{owner}/{repo}",
        local_path=None,
    )


# --- Unit tests ------------------------------------------------------------


class TestResolveFromOwnerRepo(unittest.TestCase):
    def test_basic(self) -> None:
        r = resolve_from_owner_repo("alice", "demo")
        self.assertEqual(r.owner, "alice")
        self.assertEqual(r.repo, "demo")
        self.assertEqual(r.remote, "https://github.com/alice/demo")
        self.assertIsNone(r.local_path)

    def test_preserves_case(self) -> None:
        # GitHub preserves case in the URL.
        r = resolve_from_owner_repo("Alice", "Demo")
        self.assertEqual(r.owner, "Alice")
        self.assertEqual(r.repo, "Demo")
        self.assertEqual(r.remote, "https://github.com/Alice/Demo")

    def test_strips_whitespace(self) -> None:
        r = resolve_from_owner_repo("  alice  ", "  demo  ")
        self.assertEqual(r.owner, "alice")
        self.assertEqual(r.repo, "demo")

    def test_repo_with_dash_dot_underscore(self) -> None:
        r = resolve_from_owner_repo("alice", "ai.issue_solver-v2")
        self.assertEqual(r.repo, "ai.issue_solver-v2")

    def test_owner_with_dash(self) -> None:
        # Owner names allow '-' (orgs often have dashes).
        r = resolve_from_owner_repo("my-org", "demo")
        self.assertEqual(r.owner, "my-org")

    def test_owner_with_underscore_rejected(self) -> None:
        # Per #470 review: owner names must NOT contain '_'.
        with self.assertRaises(ValueError):
            resolve_from_owner_repo("my_owner", "demo")

    def test_owner_with_dot_rejected(self) -> None:
        # Per #470 review: owner names must NOT contain '.'.
        with self.assertRaises(ValueError):
            resolve_from_owner_repo("my.owner", "demo")

    def test_owner_with_dash_ok(self) -> None:
        # Sanity: '-' IS still allowed in owner names.
        r = resolve_from_owner_repo("my-org-2024", "demo")
        self.assertEqual(r.owner, "my-org-2024")

    def test_owner_leading_dash_rejected(self) -> None:
        # Per #470 review: owner must START with alnum, not '-'.
        with self.assertRaises(ValueError):
            resolve_from_owner_repo("-owner", "demo")

    def test_owner_trailing_dash_rejected(self) -> None:
        # Per #470 review: owner must END with alnum, not '-'.
        with self.assertRaises(ValueError):
            resolve_from_owner_repo("owner-", "demo")

    def test_owner_only_dashes_rejected(self) -> None:
        # '-' alone is not a valid owner.
        with self.assertRaises(ValueError):
            resolve_from_owner_repo("---", "demo")

    def test_repo_leading_dash_rejected(self) -> None:
        # Same rule applies to repo: start with alnum.
        with self.assertRaises(ValueError):
            resolve_from_owner_repo("alice", "-repo")

    def test_repo_trailing_dash_rejected(self) -> None:
        with self.assertRaises(ValueError):
            resolve_from_owner_repo("alice", "repo-")

    def test_repo_only_dots_rejected(self) -> None:
        # Repo allows '.' but must start/end with alnum.
        with self.assertRaises(ValueError):
            resolve_from_owner_repo("alice", "...")

    def test_empty_owner_raises(self) -> None:
        with self.assertRaises(ValueError):
            resolve_from_owner_repo("", "demo")

    def test_empty_repo_raises(self) -> None:
        with self.assertRaises(ValueError):
            resolve_from_owner_repo("alice", "")

    def test_slash_in_owner_raises(self) -> None:
        with self.assertRaises(ValueError):
            resolve_from_owner_repo("alice/bob", "demo")

    def test_slash_in_repo_raises(self) -> None:
        with self.assertRaises(ValueError):
            resolve_from_owner_repo("alice", "demo/sub")

    def test_owner_too_long_raises(self) -> None:
        # GitHub owner names are max 39 chars.
        with self.assertRaises(ValueError):
            resolve_from_owner_repo("a" * 40, "demo")

    def test_repo_too_long_raises(self) -> None:
        with self.assertRaises(ValueError):
            resolve_from_owner_repo("alice", "a" * 101)

    def test_no_api_call_made(self) -> None:
        # Smoke: the function must complete without network.
        # We assert by patching subprocess and socket; if either was
        # invoked we'd notice via the mock.
        with mock.patch("subprocess.run") as sr, mock.patch(
            "urllib.request.urlopen"
        ) as urlopen:
            resolve_from_owner_repo("alice", "demo")
            sr.assert_not_called()
            urlopen.assert_not_called()


class TestParseGitRemoteUrl(unittest.TestCase):
    """Direct tests of the URL parser, since it's the trickiest piece."""

    def test_https_with_git_suffix(self) -> None:
        from ais_core.repo_resolve import _parse_git_remote_url
        self.assertEqual(
            _parse_git_remote_url("https://github.com/alice/demo.git"),
            ("alice", "demo"),
        )

    def test_https_without_git_suffix(self) -> None:
        from ais_core.repo_resolve import _parse_git_remote_url
        self.assertEqual(
            _parse_git_remote_url("https://github.com/alice/demo"),
            ("alice", "demo"),
        )

    def test_https_with_trailing_slash(self) -> None:
        from ais_core.repo_resolve import _parse_git_remote_url
        self.assertEqual(
            _parse_git_remote_url("https://github.com/alice/demo/"),
            ("alice", "demo"),
        )

    def test_https_with_www_prefix(self) -> None:
        # GitHub accepts www.github.com as a canonical alias.
        from ais_core.repo_resolve import _parse_git_remote_url
        self.assertEqual(
            _parse_git_remote_url("https://www.github.com/alice/demo.git"),
            ("alice", "demo"),
        )

    def test_ssh_short_form(self) -> None:
        from ais_core.repo_resolve import _parse_git_remote_url
        self.assertEqual(
            _parse_git_remote_url("git@github.com:alice/demo.git"),
            ("alice", "demo"),
        )

    def test_ssh_url_form(self) -> None:
        from ais_core.repo_resolve import _parse_git_remote_url
        self.assertEqual(
            _parse_git_remote_url("ssh://git@github.com/alice/demo.git"),
            ("alice", "demo"),
        )

    def test_ssh_url_with_www_prefix(self) -> None:
        from ais_core.repo_resolve import _parse_git_remote_url
        self.assertEqual(
            _parse_git_remote_url("ssh://git@www.github.com/alice/demo.git"),
            ("alice", "demo"),
        )

    # --- exact /owner/repo path enforcement ---

    def test_extra_path_segments_rejected(self) -> None:
        # Per #470 review: GitHub URLs are EXACTLY /owner/repo[.git].
        # Subgroups like /org/sub/repo must be rejected, not silently
        # truncated to the last two segments.
        from ais_core.repo_resolve import _parse_git_remote_url
        with self.assertRaises(ValueError):
            _parse_git_remote_url("https://github.com/org/sub/repo.git")

    def test_single_segment_path_rejected(self) -> None:
        from ais_core.repo_resolve import _parse_git_remote_url
        with self.assertRaises(ValueError):
            _parse_git_remote_url("https://github.com/justarepo.git")

    def test_empty_path_rejected(self) -> None:
        from ais_core.repo_resolve import _parse_git_remote_url
        with self.assertRaises(ValueError):
            _parse_git_remote_url("https://github.com/")

    def test_three_segment_ssh_rejected(self) -> None:
        from ais_core.repo_resolve import _parse_git_remote_url
        with self.assertRaises(ValueError):
            _parse_git_remote_url("git@github.com:org/sub/repo.git")

    # --- non-GitHub host rejection ---

    def test_gitlab_https_rejected(self) -> None:
        from ais_core.repo_resolve import _parse_git_remote_url
        with self.assertRaises(ValueError):
            _parse_git_remote_url("https://gitlab.com/alice/demo.git")

    def test_gitlab_ssh_rejected(self) -> None:
        from ais_core.repo_resolve import _parse_git_remote_url
        with self.assertRaises(ValueError):
            _parse_git_remote_url("git@gitlab.com:alice/demo.git")

    def test_bitbucket_rejected(self) -> None:
        from ais_core.repo_resolve import _parse_git_remote_url
        with self.assertRaises(ValueError):
            _parse_git_remote_url("https://bitbucket.org/alice/demo.git")

    def test_self_hosted_rejected(self) -> None:
        from ais_core.repo_resolve import _parse_git_remote_url
        with self.assertRaises(ValueError):
            _parse_git_remote_url("https://git.example.com/alice/demo.git")

    def test_invalid_url_raises(self) -> None:
        from ais_core.repo_resolve import _parse_git_remote_url
        with self.assertRaises(ValueError):
            _parse_git_remote_url("not a url")

    def test_empty_url_raises(self) -> None:
        from ais_core.repo_resolve import _parse_git_remote_url
        with self.assertRaises(ValueError):
            _parse_git_remote_url("")


class TestResolveFromGitRemote(unittest.TestCase):
    def setUp(self) -> None:
        # Create a tiny local git repo with a remote.origin.url set.
        self.tmpdir = Path(tempfile.mkdtemp(prefix="ais-repo-resolve-"))
        self._run_git("init")
        self._run_git("config", "user.email", "test@example.com")
        self._run_git("config", "user.name", "Test")
        self._run_git("config", "remote.origin.url", "https://github.com/alice/demo.git")

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run_git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.tmpdir), *args],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def test_basic(self) -> None:
        r = resolve_from_git_remote(str(self.tmpdir))
        self.assertEqual(r.owner, "alice")
        self.assertEqual(r.repo, "demo")
        self.assertEqual(r.remote, "https://github.com/alice/demo")
        self.assertEqual(r.local_path, str(self.tmpdir))

    def test_ssh_remote(self) -> None:
        self._run_git("config", "remote.origin.url", "git@github.com:alice/demo.git")
        r = resolve_from_git_remote(str(self.tmpdir))
        self.assertEqual(r.owner, "alice")
        self.assertEqual(r.repo, "demo")

    def test_path_is_not_dir(self) -> None:
        with self.assertRaises(ValueError):
            resolve_from_git_remote("/nonexistent/path/that/is/not/here")

    def test_missing_remote_url(self) -> None:
        # Init a fresh repo WITHOUT setting remote.origin.url.
        empty = Path(tempfile.mkdtemp(prefix="ais-repo-empty-"))
        try:
            subprocess.run(
                ["git", "-C", str(empty), "init"],
                check=True,
                capture_output=True,
            )
            with self.assertRaises(ValueError):
                resolve_from_git_remote(str(empty))
        finally:
            import shutil
            shutil.rmtree(empty, ignore_errors=True)


class TestResolveRepoHint(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp(prefix="ais-hint-"))
        subprocess.run(
            ["git", "-C", str(self.tmpdir), "init"],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(self.tmpdir), "config", "remote.origin.url",
             "https://github.com/bob/local-checkout.git"],
            check=True, capture_output=True,
        )
        # Stash + restore GITHUB_USER around each test.
        self._saved_github_user = os.environ.get("GITHUB_USER")
        self._saved_cwd = os.getcwd()
        os.chdir(self.tmpdir)  # so Path(hint).is_dir() works for relative paths

    def tearDown(self) -> None:
        import shutil
        os.chdir(self._saved_cwd)
        if self._saved_github_user is None:
            os.environ.pop("GITHUB_USER", None)
        else:
            os.environ["GITHUB_USER"] = self._saved_github_user
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_owner_repo_format(self) -> None:
        r = resolve_repo_hint("alice/other-repo")
        self.assertEqual(r.owner, "alice")
        self.assertEqual(r.repo, "other-repo")
        self.assertIsNone(r.local_path)

    def test_directory_format_absolute(self) -> None:
        r = resolve_repo_hint(str(self.tmpdir))
        self.assertEqual(r.owner, "bob")
        self.assertEqual(r.repo, "local-checkout")
        self.assertEqual(r.local_path, str(self.tmpdir))

    def test_bare_repo_uses_github_user_env(self) -> None:
        os.environ["GITHUB_USER"] = "default-owner"
        r = resolve_repo_hint("just-a-repo")
        self.assertEqual(r.owner, "default-owner")
        self.assertEqual(r.repo, "just-a-repo")

    def test_bare_repo_without_github_user_raises(self) -> None:
        os.environ.pop("GITHUB_USER", None)
        with self.assertRaises(ValueError):
            resolve_repo_hint("just-a-repo")

    def test_empty_hint_raises(self) -> None:
        with self.assertRaises(ValueError):
            resolve_repo_hint("")

    def test_whitespace_hint_raises(self) -> None:
        with self.assertRaises(ValueError):
            resolve_repo_hint("   ")


# --- Characterization + Comparison tests ----------------------------------


class TestCharacterizationLegacy(unittest.TestCase):
    """Pin the pre-#470 behaviour so we can detect drift during refactor."""

    def test_legacy_resolve_basic(self) -> None:
        # Owner from auth/config, repo from --repo CLI arg.
        r = _legacy_resolve("SaJaToGu", "ai-issue-solver")
        self.assertEqual(r.owner, "SaJaToGu")
        self.assertEqual(r.repo, "ai-issue-solver")
        self.assertEqual(r.remote, "https://github.com/SaJaToGu/ai-issue-solver")
        self.assertIsNone(r.local_path)

    def test_legacy_resolve_strips_nothing(self) -> None:
        # The legacy code did NOT validate input. This test pins that
        # the new library function tightens input (separate test).
        r = _legacy_resolve("SaJaToGu", "ai-issue-solver  ")
        # Legacy passed through with whitespace; we DO NOT preserve that.
        # This documents the behavior the library function CHANGES.
        self.assertEqual(r.repo, "ai-issue-solver  ")


class TestComparisonLegacyVsLibrary(unittest.TestCase):
    """For the simple (owner, repo) case, library and legacy must agree."""

    def test_agrees_on_basic(self) -> None:
        lib = resolve_from_owner_repo("SaJaToGu", "ai-issue-solver")
        leg = _legacy_resolve("SaJaToGu", "ai-issue-solver")
        self.assertEqual(lib, leg)

    def test_agrees_on_realistic_owners(self) -> None:
        for owner, repo in [
            ("SaJaToGu", "ai-issue-solver"),
            ("python", "cpython"),
            ("microsoft", "TypeScript"),
        ]:
            with self.subTest(owner=owner, repo=repo):
                self.assertEqual(
                    resolve_from_owner_repo(owner, repo),
                    _legacy_resolve(owner, repo),
                )


class TestNoNetworkAccess(unittest.TestCase):
    """All repo_resolve functions must work fully offline."""

    def test_resolve_from_owner_repo_no_network(self) -> None:
        # Block all network at the socket layer; the function should
        # still succeed.
        import socket
        original_socket = socket.socket
        with mock.patch("socket.socket", side_effect=AssertionError("network call")):
            r = resolve_from_owner_repo("alice", "demo")
        self.assertEqual(r.owner, "alice")

    def test_resolve_from_git_remote_uses_local_git_only(self) -> None:
        # Create a local repo and verify resolve_from_git_remote
        # only invokes the local git binary (no URL fetches).
        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            subprocess.run(
                ["git", "-C", str(tmpdir), "init"],
                check=True, capture_output=True,
            )
            subprocess.run(
                ["git", "-C", str(tmpdir), "config", "remote.origin.url",
                 "https://github.com/alice/demo.git"],
                check=True, capture_output=True,
            )
            with mock.patch("urllib.request.urlopen") as urlopen:
                r = resolve_from_git_remote(str(tmpdir))
            urlopen.assert_not_called()
        self.assertEqual(r.owner, "alice")


if __name__ == "__main__":
    unittest.main()
