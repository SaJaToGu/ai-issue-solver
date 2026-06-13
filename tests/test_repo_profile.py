from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from repo_profile import (  # noqa: E402
    GitHubRepoProfileProvider,
    LocalRepoProfileProvider,
    RepoProfile,
    RepoProfileProvider,
    provider_targets,
)


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses):
        self.responses = responses
        self.requests = []
        self.headers = {}

    def get(self, url):
        path = url.replace("https://api.github.com", "")
        self.requests.append(path)
        payload = self.responses.get(path)
        if payload is None:
            return FakeResponse({}, status_code=404)
        return FakeResponse(payload)


class RepoProfileTests(unittest.TestCase):
    def test_profile_model_exposes_model_selection_context(self):
        profile = RepoProfile(
            provider="gitlab",
            repo="group/demo",
            dominant_language="python",
            language_percentages={"python": 100.0},
            repo_kind="python",
            framework_hints=("fastapi",),
            test_hints=("python -m pytest",),
            recommended_worker="opencode",
            python_required=True,
        )

        context = profile.as_model_selection_context()

        self.assertEqual(context["provider"], "gitlab")
        self.assertEqual(context["repo_type"], "python")
        self.assertEqual(context["framework_hints"], ["fastapi"])
        self.assertTrue(context["python_required"])

    def test_provider_targets_include_non_github_forges(self):
        targets = provider_targets()

        self.assertIn("github", targets)
        self.assertIn("gitlab", targets)
        self.assertIn("forgejo", targets)
        self.assertIn("gitea", targets)
        self.assertIn("codeberg", targets)
        self.assertIn("bitbucket", targets)
        self.assertIn("local", targets)

    def test_github_provider_uses_languages_metadata_topics_and_tree(self):
        session = FakeSession(
            {
                "/repos/example/demo": {
                    "default_branch": "main",
                    "language": "Python",
                    "archived": False,
                    "private": True,
                    "size": 42,
                    "description": "Demo repo",
                },
                "/repos/example/demo/languages": {"Python": 900, "R": 100},
                "/repos/example/demo/topics": {"names": ["fastapi"]},
                "/repos/example/demo/git/trees/main?recursive=1": {
                    "tree": [
                        {"type": "blob", "path": "pyproject.toml"},
                        {"type": "blob", "path": "tests/test_app.py"},
                    ]
                },
            }
        )
        provider = GitHubRepoProfileProvider(session=session)

        profile = provider.get_profile("example/demo")

        self.assertEqual(profile.provider, "github")
        self.assertEqual(profile.repo, "example/demo")
        self.assertEqual(profile.dominant_language, "python")
        self.assertEqual(profile.language_percentages, {"python": 90.0, "r": 10.0})
        self.assertEqual(profile.repo_kind, "python")
        self.assertIn("fastapi", profile.framework_hints)
        self.assertIn("python -m unittest discover -s tests", profile.test_hints)
        self.assertTrue(profile.python_required)
        self.assertEqual(profile.default_branch, "main")
        self.assertTrue(profile.is_private)

    def test_local_provider_uses_marker_files_without_remote_api(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "DESCRIPTION").write_text("Package: demo\n", encoding="utf-8")
            (root / "renv.lock").write_text("{}\n", encoding="utf-8")
            (root / "tests" / "testthat").mkdir(parents=True)
            (root / "tests" / "testthat" / "test-demo.R").write_text("testthat::test_that('x', {})\n", encoding="utf-8")

            profile = LocalRepoProfileProvider(root).get_profile("local/demo")

        self.assertEqual(profile.provider, "local")
        self.assertEqual(profile.repo, "local/demo")
        self.assertEqual(profile.dominant_language, "r")
        self.assertEqual(profile.repo_kind, "r")
        self.assertIn("r", profile.framework_hints)
        self.assertIn("Rscript -e 'testthat::test_dir(\"tests/testthat\")'", profile.test_hints)
        self.assertFalse(profile.python_required)

    def test_provider_interface_is_provider_neutral(self):
        self.assertTrue(issubclass(GitHubRepoProfileProvider, RepoProfileProvider))
        self.assertTrue(issubclass(LocalRepoProfileProvider, RepoProfileProvider))


if __name__ == "__main__":
    unittest.main()
