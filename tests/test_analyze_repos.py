import base64
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from analyze_repos import (  # noqa: E402
    analyze_repo,
    find_risky_generated_files,
    has_ci_workflow,
    has_tests,
    is_code_project,
)


class FakeGitHubClient:
    def __init__(self, paths=None, readme_size=500, files=None, dirs=None,
                 labels=None, issues=None, contents=None):
        self.paths = paths or []
        self.readme_size = readme_size
        self.files = set(files or [])
        self.dirs = set(dirs or [])
        self._labels = labels or []
        self._issues = issues or []
        self._contents = contents or {}

    def get_repo_tree_paths(self, owner, repo, branch):
        return self.paths

    def get_readme_length(self, owner, repo):
        return self.readme_size

    def repo_has_file(self, owner, repo, filepath):
        return filepath in self.files

    def repo_has_dir(self, owner, repo, dirpath):
        return dirpath in self.dirs

    def get(self, path, **params):
        lowered = path.lower()
        if lowered.rstrip('/').endswith('/labels'):
            return self._labels
        if '/contents/' in lowered:
            filepath = path.split('/contents/', 1)[1]
            content = self._contents.get(filepath)
            if content is not None:
                encoded = base64.b64encode(content.encode()).decode()
                return {
                    "content": encoded,
                    "encoding": "base64",
                    "path": filepath,
                }
            return None
        return None

    def get_all_pages(self, path, **params):
        if '/issues' in path.lower():
            return self._issues
        return []


def repo_fixture(**overrides):
    pushed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    data = {
        "name": "demo",
        "html_url": "https://github.com/example/demo",
        "language": None,
        "fork": False,
        "stargazers_count": 0,
        "description": "Demo project",
        "topics": ["demo"],
        "pushed_at": pushed_at,
        "default_branch": "main",
        "license": {"key": "mit"},
    }
    data.update(overrides)
    return data


class AnalyzerHelperTests(unittest.TestCase):
    def test_detects_code_project_from_manifest_or_extension(self):
        self.assertTrue(is_code_project({}, ["pyproject.toml"]))
        self.assertTrue(is_code_project({}, ["src/app.py"]))
        self.assertFalse(is_code_project({}, ["README.md", "docs/guide.md"]))

    def test_detects_tests_and_ci_workflows(self):
        self.assertTrue(has_tests(["tests/test_app.py"]))
        self.assertTrue(has_tests(["src/app.test.ts"]))
        self.assertTrue(has_ci_workflow([".github/workflows/ci.yml"]))
        self.assertFalse(has_ci_workflow([".github/dependabot.yml"]))

    def test_detects_risky_generated_files(self):
        paths = ["src/app.py", "dist/bundle.js", "__pycache__/app.cpython-312.pyc"]
        self.assertEqual(
            find_risky_generated_files(paths),
            ["dist/bundle.js", "__pycache__/app.cpython-312.pyc"],
        )


class AnalyzeRepoTests(unittest.TestCase):
    def test_code_repo_without_tests_or_ci_gets_precise_findings(self):
        client = FakeGitHubClient(
            paths=["pyproject.toml", "src/app.py", "dist/bundle.js"],
            files={".gitignore"},
        )

        result = analyze_repo(client, "example", repo_fixture())

        self.assertIn("missing_tests", result["findings"])
        self.assertIn("missing_ci", result["findings"])
        self.assertIn("risky_generated_files", result["findings"])
        details = result["finding_details"]
        self.assertIn("pyproject.toml", details["missing_tests"])
        self.assertIn(".github/workflows", details["missing_ci"])
        self.assertIn("dist/bundle.js", details["risky_generated_files"])

    def test_docs_only_repo_does_not_get_tests_or_ci_findings(self):
        client = FakeGitHubClient(
            paths=["README.md", "docs/guide.md"],
            files={".gitignore"},
        )

        result = analyze_repo(client, "example", repo_fixture(language=None))

        self.assertNotIn("missing_tests", result["findings"])
        self.assertNotIn("missing_ci", result["findings"])

    def test_very_stale_repo_uses_stronger_finding(self):
        old_push = (
            datetime.now(timezone.utc) - timedelta(days=1500)
        ).isoformat().replace("+00:00", "Z")
        client = FakeGitHubClient(
            paths=["src/app.py", "tests/test_app.py", ".github/workflows/ci.yml"],
            files={".gitignore"},
        )

        result = analyze_repo(client, "example", repo_fixture(pushed_at=old_push))

        self.assertIn("very_stale_repo", result["findings"])
        self.assertNotIn("stale_repo", result["findings"])
        self.assertIn("Letzter Push", result["finding_details"]["very_stale_repo"])


class LabelTaxonomyTests(unittest.TestCase):
    def test_repo_without_taxonomy_doc_gets_finding(self):
        client = FakeGitHubClient(
            paths=["src/app.py"],
        )
        result = analyze_repo(client, "example", repo_fixture())
        self.assertIn("label_taxonomy_exists", result["findings"])

    def test_repo_with_taxonomy_file_skips_finding(self):
        client = FakeGitHubClient(
            paths=["docs/label_taxonomy.md", "src/app.py"],
        )
        result = analyze_repo(client, "example", repo_fixture())
        self.assertNotIn("label_taxonomy_exists", result["findings"])

    def test_repo_with_contributing_mentioning_labels_skips_finding(self):
        client = FakeGitHubClient(
            paths=["CONTRIBUTING.md", "src/app.py"],
            contents={"CONTRIBUTING.md": "# Contributing\n\n## Labels\nUse bug, feature."},
        )
        result = analyze_repo(client, "example", repo_fixture())
        self.assertNotIn("label_taxonomy_exists", result["findings"])


class LabelUsageHealthTests(unittest.TestCase):
    def test_unused_labels_get_flagged(self):
        client = FakeGitHubClient(
            paths=["src/app.py"],
            labels=[{"name": "bug"}, {"name": "feature"}, {"name": "unused-label"}],
            issues=[{"number": 1, "labels": [{"name": "bug"}]}],
        )
        result = analyze_repo(client, "example", repo_fixture())
        self.assertIn("label_usage_health", result["findings"])
        self.assertIn("unused-label", result["finding_details"]["label_usage_health"])

    def test_untriaged_issues_get_flagged(self):
        client = FakeGitHubClient(
            paths=["src/app.py"],
            labels=[{"name": "bug"}, {"name": "feature"}],
            issues=[
                {"number": 1, "labels": [{"name": "bug"}]},
                {"number": 2, "labels": []},
            ],
        )
        result = analyze_repo(client, "example", repo_fixture())
        self.assertIn("label_usage_health", result["findings"])
        self.assertIn("#2", result["finding_details"]["label_usage_health"])

    def test_healthy_label_usage_no_finding(self):
        client = FakeGitHubClient(
            paths=["src/app.py"],
            labels=[{"name": "bug"}],
            issues=[{"number": 1, "labels": [{"name": "bug"}]}],
        )
        result = analyze_repo(client, "example", repo_fixture())
        self.assertNotIn("label_usage_health", result["findings"])

    def test_inconsistent_labels_reported(self):
        client = FakeGitHubClient(
            paths=["docs/label_taxonomy.md", "src/app.py"],
            labels=[{"name": "bug"}, {"name": "custom-label"}],
            issues=[{"number": 1, "labels": [{"name": "custom-label"}]}],
            contents={"docs/label_taxonomy.md": "| `bug` | Bug fixes |"},
        )
        result = analyze_repo(client, "example", repo_fixture())
        self.assertIn("label_usage_health", result["findings"])
        self.assertIn("custom-label",
                       result["finding_details"]["label_usage_health"])


if __name__ == "__main__":
    unittest.main()
