import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from github_summary import (  # noqa: E402
    GitHubClient,
    build_repo_summary,
    format_issue,
    format_run,
    short_age,
    trim_title,
)


class FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text

    def json(self):
        return self._payload


class FakeGitHubSession:
    def __init__(self):
        self.headers = {}
        self.requests = []

    def get(self, url, params=None):
        self.requests.append((url, dict(params or {})))
        if url.endswith("/repos/test-owner/demo/issues"):
            return FakeResponse(200, [
                {"number": 1, "title": "Open issue", "updated_at": "2026-05-20T10:00:00Z"},
                {
                    "number": 2,
                    "title": "PR disguised as issue",
                    "pull_request": {},
                    "updated_at": "2026-05-20T10:00:00Z",
                },
            ])
        if url.endswith("/repos/test-owner/demo/pulls"):
            if params and params.get("state") == "open":
                return FakeResponse(200, [
                    {
                        "number": 3,
                        "title": "Open PR",
                        "updated_at": "2026-05-20T09:00:00Z",
                        "user": {"login": "alice"},
                    }
                ])
            return FakeResponse(200, [
                {
                    "number": 4,
                    "title": "Merged PR",
                    "merged_at": "2026-05-19T18:00:00Z",
                    "updated_at": "2026-05-19T18:00:00Z",
                    "user": {"login": "bob"},
                },
                {
                    "number": 6,
                    "title": "Old merged PR",
                    "merged_at": "2026-04-19T18:00:00Z",
                    "updated_at": "2026-04-19T18:00:00Z",
                    "user": {"login": "dan"},
                },
                {
                    "number": 5,
                    "title": "Closed PR",
                    "merged_at": None,
                    "updated_at": "2026-05-18T18:00:00Z",
                    "user": {"login": "carol"},
                },
            ])
        if url.endswith("/repos/test-owner/demo/actions/runs"):
            return FakeResponse(200, {
                "workflow_runs": [
                    {
                        "name": "CI",
                        "head_branch": "main",
                        "conclusion": "failure",
                        "updated_at": "2026-05-20T08:00:00Z",
                    },
                    {
                        "name": "Release",
                        "head_branch": "main",
                        "conclusion": "success",
                        "updated_at": "2026-05-20T07:00:00Z",
                    },
                    {
                        "name": "Lint",
                        "head_branch": "feature",
                        "conclusion": "timed_out",
                        "updated_at": "2026-05-20T06:00:00Z",
                    },
                ]
            })
        return FakeResponse(404, {"message": "Not found"})


class GitHubSummaryTests(unittest.TestCase):
    def make_client(self):
        client = GitHubClient.__new__(GitHubClient)
        client.owner = "test-owner"
        client.session = FakeGitHubSession()
        return client

    def test_build_repo_summary_filters_github_api_results(self):
        client = self.make_client()

        summary = build_repo_summary(
            client,
            "demo",
            datetime(2026, 5, 1, tzinfo=timezone.utc),
            datetime(2026, 5, 1, tzinfo=timezone.utc),
        )

        self.assertEqual([issue["number"] for issue in summary.open_issues], [1])
        self.assertEqual([pull["number"] for pull in summary.open_prs], [3])
        self.assertEqual([pull["number"] for pull in summary.merged_prs], [4])
        self.assertEqual([run["name"] for run in summary.failed_runs], ["CI", "Lint"])

    def test_failed_runs_use_created_filter_without_github_cli(self):
        client = self.make_client()

        client.get_failed_runs("demo", datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc))

        run_request = [
            params for url, params in client.session.requests
            if url.endswith("/actions/runs")
        ][0]
        self.assertEqual(run_request["status"], "completed")
        self.assertEqual(run_request["created"], ">=2026-05-01T12:00:00Z")

    def test_format_helpers_keep_output_compact(self):
        now = datetime(2026, 5, 20, 12, 0, tzinfo=timezone.utc)

        self.assertEqual(short_age("2026-05-20T10:30:00Z", now=now), "vor 1h")
        self.assertTrue(trim_title("x" * 100, 20).endswith("…"))
        self.assertIn("#7", format_issue({
            "number": 7,
            "title": "Fix summary",
            "updated_at": "2026-05-20T10:00:00Z",
        }))
        self.assertIn("CI [main] failure", format_run({
            "name": "CI",
            "head_branch": "main",
            "conclusion": "failure",
            "updated_at": "2026-05-20T10:00:00Z",
        }))


if __name__ == "__main__":
    unittest.main()
