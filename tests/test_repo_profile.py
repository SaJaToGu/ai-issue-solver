from __future__ import annotations

import json
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
    build_repo_profile,
    collect_test_hints_from_workflows,
    filter_secret_paths,
    is_secret_path,
    provider_targets,
    select_profile_provider,
    serialize_repo_profile,
    summarize_remote_state,
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
        if path not in self.responses:
            return FakeResponse({}, status_code=404)
        payload = self.responses[path]
        if isinstance(payload, Exception):
            raise payload
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
            source="github_rest",
        )

        context = profile.as_model_selection_context()

        self.assertEqual(context["provider"], "gitlab")
        self.assertEqual(context["repo_type"], "python")
        self.assertEqual(context["framework_hints"], ["fastapi"])
        self.assertTrue(context["python_required"])
        self.assertEqual(context["source"], "github_rest")

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
                        {"type": "blob", "path": ".env"},
                    ]
                },
                "/repos/example/demo/contents/.github/workflows": [
                    {"type": "file", "name": "ci.yml", "path": ".github/workflows/ci.yml", "download_url": "x"}
                ],
                "/repos/example/demo/pulls?state=open&per_page=50": [
                    {"number": 12, "head": {"ref": "ai/fix-issue-12"}},
                    {"number": 17, "head": {"ref": "feature/manual"}},
                ],
                "/repos/example/demo/issues?state=open&per_page=50": [
                    {"number": 1},
                    {"number": 2, "pull_request": {}},
                    {"number": 3},
                ],
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
        self.assertEqual(profile.source, "github_rest")
        self.assertNotIn(".env", profile.marker_files)
        self.assertEqual(profile.extra["workflows"][0]["name"], "ci.yml")
        remote_state = profile.extra["remote_state"]
        self.assertEqual(remote_state["open_pull_requests"], 2)
        self.assertEqual(remote_state["open_pull_request_numbers"], [12, 17])
        self.assertEqual(remote_state["open_issues"], 2)
        self.assertEqual(remote_state["open_issue_numbers"], [1, 3])
        self.assertEqual(remote_state["existing_solver_branches"], ["ai/fix-issue-12"])

    def test_local_provider_uses_marker_files_without_remote_api(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "DESCRIPTION").write_text("Package: demo\n", encoding="utf-8")
            (root / "renv.lock").write_text("{}\n", encoding="utf-8")
            (root / ".env").write_text("SECRET=topsecret\n", encoding="utf-8")
            (root / "tests" / "testthat").mkdir(parents=True)
            (root / "tests" / "testthat" / "test-demo.R").write_text("testthat::test_that('x', {})\n", encoding="utf-8")

            profile = LocalRepoProfileProvider(root).get_profile("local/demo")

        self.assertEqual(profile.provider, "local")
        self.assertEqual(profile.repo, "local/demo")
        self.assertEqual(profile.dominant_language, "r")
        self.assertEqual(profile.repo_kind, "r")
        self.assertEqual(profile.source, "local_marker_heuristics")
        self.assertIn("r", profile.framework_hints)
        self.assertIn("Rscript -e 'testthat::test_dir(\"tests/testthat\")'", profile.test_hints)
        self.assertFalse(profile.python_required)
        self.assertNotIn(".env", profile.marker_files)

    def test_provider_interface_is_provider_neutral(self):
        self.assertTrue(issubclass(GitHubRepoProfileProvider, RepoProfileProvider))
        self.assertTrue(issubclass(LocalRepoProfileProvider, RepoProfileProvider))


class SecretPathSafetyTests(unittest.TestCase):
    def test_is_secret_path_recognises_known_secret_files(self):
        for path in (
            ".env",
            ".env.local",
            "config/.env",
            "secrets.json",
            "auth.json",
            ".github/secrets/keys.json",
            "secrets/database.yml",
        ):
            with self.subTest(path=path):
                self.assertTrue(is_secret_path(path), path)

    def test_is_secret_path_ignores_normal_files(self):
        for path in (
            "src/app.py",
            "tests/test_app.py",
            "README.md",
            "pyproject.toml",
            "scripts/run.py",
        ):
            with self.subTest(path=path):
                self.assertFalse(is_secret_path(path), path)

    def test_filter_secret_paths_keeps_only_safe_paths(self):
        paths = [
            "src/app.py",
            ".env",
            "secrets/db.yml",
            "tests/test_app.py",
            "auth.json",
        ]
        safe = filter_secret_paths(paths)
        self.assertEqual(
            sorted(safe),
            sorted(["src/app.py", "tests/test_app.py"]),
        )

    def test_local_provider_never_returns_secret_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("# ok\n", encoding="utf-8")
            (root / ".env").write_text("KEY=topsecret\n", encoding="utf-8")
            (root / ".env.local").write_text("KEY=local\n", encoding="utf-8")
            (root / "secrets.json").write_text("{}", encoding="utf-8")
            (root / "auth.json").write_text("{}", encoding="utf-8")
            (root / "private").mkdir()
            (root / "private" / "creds").mkdir()
            (root / "private" / "creds" / "key.pem").write_text("---", encoding="utf-8")
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")

            profile = LocalRepoProfileProvider(root).get_profile("local/demo")

        joined = "\n".join(profile.marker_files)
        for forbidden in (".env", ".env.local", "secrets.json", "auth.json", "private/"):
            self.assertNotIn(forbidden, joined)


class ProviderSelectionTests(unittest.TestCase):
    def test_select_profile_provider_uses_github_when_session_and_token_available(self):
        session = FakeSession({})
        provider = select_profile_provider(
            "owner/demo",
            token="ghp_dummy",
            session=session,
            env={},
        )
        self.assertIsInstance(provider, GitHubRepoProfileProvider)

    def test_select_profile_provider_falls_back_to_local_without_token(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = select_profile_provider(
                "owner/demo",
                env={},
                local_root=tmpdir,
                prefer="github",
            )
            self.assertIsInstance(provider, LocalRepoProfileProvider)

    def test_select_profile_provider_honours_offline_flag(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = select_profile_provider(
                "owner/demo",
                token="ghp_dummy",
                env={},
                local_root=tmpdir,
                offline=True,
            )
            self.assertIsInstance(provider, LocalRepoProfileProvider)

    def test_select_profile_provider_accepts_prefer_local(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = select_profile_provider(
                "owner/demo",
                token="ghp_dummy",
                env={},
                local_root=tmpdir,
                prefer="local",
            )
            self.assertIsInstance(provider, LocalRepoProfileProvider)

    def test_build_repo_profile_github_first(self):
        session = FakeSession(
            {
                "/repos/example/demo": {"default_branch": "main", "private": False, "size": 1, "description": ""},
                "/repos/example/demo/languages": {"Python": 1000},
                "/repos/example/demo/topics": {"names": []},
                "/repos/example/demo/git/trees/main?recursive=1": {
                    "tree": [{"type": "blob", "path": "pyproject.toml"}]
                },
                "/repos/example/demo/contents/.github/workflows": [],
                "/repos/example/demo/pulls?state=open&per_page=50": [],
                "/repos/example/demo/issues?state=open&per_page=50": [],
            }
        )
        profile = build_repo_profile(
            "example/demo",
            token="ghp_dummy",
            session=session,
            env={},
        )
        self.assertEqual(profile.provider, "github")
        self.assertEqual(profile.source, "github_rest")
        self.assertEqual(profile.repo_kind, "python")

    def test_build_repo_profile_falls_back_to_local_on_github_error(self):
        session = FakeSession(
            {
                "/repos/example/demo": RuntimeError("boom"),
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
            profile = build_repo_profile(
                "example/demo",
                token="ghp_dummy",
                session=session,
                env={},
                local_root=root,
            )
        self.assertEqual(profile.provider, "local")
        self.assertEqual(profile.repo_kind, "python")
        self.assertEqual(profile.source, "local_marker_heuristics")

    def test_build_repo_profile_offline_uses_local(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "DESCRIPTION").write_text("Package: demo\n", encoding="utf-8")
            profile = build_repo_profile(
                "owner/demo",
                token="ghp_dummy",
                env={},
                local_root=root,
                offline=True,
            )
        self.assertEqual(profile.provider, "local")
        self.assertEqual(profile.repo_kind, "r")

    def test_serialize_repo_profile_is_json_safe(self):
        profile = RepoProfile(
            provider="github",
            repo="example/demo",
            dominant_language="python",
            language_percentages={"python": 100.0},
            repo_kind="python",
            framework_hints=("fastapi",),
            test_hints=("python -m pytest",),
            recommended_worker="opencode",
            python_required=True,
            default_branch="main",
            topics=("fastapi",),
            marker_files=("pyproject.toml",),
            source="github_rest",
            extra={
                "workflows": [{"name": "ci.yml", "path": ".github/workflows/ci.yml"}],
                "remote_state": {
                    "open_pull_requests": 1,
                    "open_issues": 0,
                    "open_issue_numbers": [],
                    "open_pull_request_numbers": [42],
                    "existing_solver_branches": ["ai/fix-issue-7"],
                },
            },
        )
        serialized = serialize_repo_profile(profile)
        self.assertEqual(serialized["repo"], "example/demo")
        self.assertEqual(serialized["source"], "github_rest")
        self.assertEqual(serialized["extra"]["workflows"][0]["name"], "ci.yml")
        json.dumps(serialized)

    def test_serialize_repo_profile_drops_secret_paths(self):
        profile = RepoProfile(
            provider="local",
            repo="local/demo",
            marker_files=("src/app.py", ".env", "secrets.json"),
        )
        serialized = serialize_repo_profile(profile)
        self.assertIn("src/app.py", serialized["marker_files"])
        self.assertNotIn(".env", serialized["marker_files"])
        self.assertNotIn("secrets.json", serialized["marker_files"])


class WorkflowAndRemoteStateTests(unittest.TestCase):
    def test_collect_test_hints_from_workflows_extracts_run_commands(self):
        workflows = [
            {
                "name": "ci.yml",
                "path": ".github/workflows/ci.yml",
                "run": "python -m pytest",
            },
            {
                "name": "lint.yml",
                "path": ".github/workflows/lint.yml",
                "scripts": ["Rscript -e 'devtools::test()'"],
            },
        ]
        hints = collect_test_hints_from_workflows(workflows, dominant_language="python")
        self.assertIn("python -m pytest", hints)
        self.assertIn("Rscript -e 'devtools::test()'", hints)
        self.assertIn("python -m pytest", hints)
        self.assertIn("github_actions: ci.yml", hints)

    def test_collect_test_hints_from_workflows_skips_secret_run_paths(self):
        workflows = [
            {
                "name": "ci.yml",
                "run": "deploy-secrets --key auth.json",
            },
        ]
        hints = collect_test_hints_from_workflows(workflows)
        self.assertNotIn("deploy-secrets --key auth.json", hints)

    def test_summarize_remote_state_normalises_inputs(self):
        summary = summarize_remote_state({
            "open_pull_requests": "3",
            "open_issues": 2,
            "open_issue_numbers": (1, 2),
            "open_pull_request_numbers": [5, 6, 7],
            "existing_solver_branches": {"ai/fix-issue-5", "ai/fix-issue-6"},
        })
        self.assertEqual(summary["open_pull_requests"], 3)
        self.assertEqual(summary["open_issues"], 2)
        self.assertEqual(tuple(summary["open_issue_numbers"]), (1, 2))
        self.assertEqual(tuple(summary["open_pull_request_numbers"]), (5, 6, 7))
        self.assertEqual(
            tuple(sorted(summary["existing_solver_branches"])),
            ("ai/fix-issue-5", "ai/fix-issue-6"),
        )

    def test_summarize_remote_state_handles_missing_inputs(self):
        summary = summarize_remote_state(None)
        self.assertEqual(summary["open_pull_requests"], 0)
        self.assertEqual(summary["open_issues"], 0)
        self.assertEqual(summary["open_issue_numbers"], ())
        self.assertEqual(summary["open_pull_request_numbers"], ())
        self.assertEqual(summary["existing_solver_branches"], ())


if __name__ == "__main__":
    unittest.main()
