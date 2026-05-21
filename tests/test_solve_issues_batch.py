import argparse
import sys
import threading
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from solve_issues_batch import (  # noqa: E402
    IssueJob,
    IssueJobResult,
    build_worker_command,
    dedupe_issue_jobs,
    discover_issue_jobs,
    run_issue_jobs,
)


class FakeBatchClient:
    def get_single_issue(self, repo, number):
        if number == 404:
            return None
        return {"number": number, "title": "Issue"}

    def get_open_issues(self, repo, label="ai-generated"):
        return [
            {"number": 7, "title": "Fix"},
            {"number": 8, "title": "Improve"},
            {"number": 8, "title": "Duplicate"},
            {"number": 9, "pull_request": {}},
        ]


class BatchRunnerTests(unittest.TestCase):
    def make_args(self, **overrides):
        defaults = {
            "model": "codex",
            "model_name": "",
            "label": "ai-generated",
            "base_branch": None,
            "dry_run": False,
            "close_issues": False,
        }
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def test_dedupe_issue_jobs_preserves_first_occurrence(self):
        jobs = dedupe_issue_jobs([
            IssueJob("demo", 7),
            IssueJob("demo", 7),
            IssueJob("other", 7),
            IssueJob("demo", 8),
        ])

        self.assertEqual(
            jobs,
            [IssueJob("demo", 7), IssueJob("other", 7), IssueJob("demo", 8)],
        )

    def test_discover_issue_jobs_filters_pull_requests_and_duplicates(self):
        jobs = discover_issue_jobs(FakeBatchClient(), ["demo"], None, "ai-generated")

        self.assertEqual(jobs, [IssueJob("demo", 7), IssueJob("demo", 8)])

    def test_discover_issue_jobs_accepts_repeated_issue_flags_once(self):
        jobs = discover_issue_jobs(FakeBatchClient(), ["demo"], [7, 7, 404], "ai-generated")

        self.assertEqual(jobs, [IssueJob("demo", 7)])

    def test_build_worker_command_forwards_solver_flags(self):
        args = self.make_args(
            model="ollama",
            model_name="llama3.2:3b",
            base_branch="develop",
            dry_run=True,
            close_issues=True,
        )

        cmd = build_worker_command(args, IssueJob("demo", 7), Path("scripts/solve_issues.py"))

        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("scripts/solve_issues.py", cmd)
        self.assertIn("--model", cmd)
        self.assertIn("ollama", cmd)
        self.assertIn("--repo", cmd)
        self.assertIn("demo", cmd)
        self.assertIn("--issue", cmd)
        self.assertIn("7", cmd)
        self.assertIn("--model-name", cmd)
        self.assertIn("llama3.2:3b", cmd)
        self.assertIn("--base-branch", cmd)
        self.assertIn("develop", cmd)
        self.assertIn("--dry-run", cmd)
        self.assertIn("--close-issues", cmd)

    def test_run_issue_jobs_continues_after_worker_failure(self):
        jobs = [IssueJob("demo", 1), IssueJob("demo", 2), IssueJob("demo", 3)]
        started = []

        def run(job):
            started.append(job.issue_number)
            if job.issue_number == 2:
                raise RuntimeError("boom")
            return IssueJobResult(job, 0, f"ok {job.issue_number}", 0.0)

        results = run_issue_jobs(jobs, workers=2, run_job_fn=run)

        self.assertEqual(sorted(started), [1, 2, 3])
        self.assertEqual(len(results), 3)
        self.assertEqual(sum(1 for result in results if result.ok), 2)
        self.assertIn("Unerwarteter Worker-Fehler: boom", "\n".join(r.output for r in results))

    def test_run_issue_jobs_uses_worker_limit(self):
        jobs = [IssueJob("demo", number) for number in range(4)]
        active = 0
        max_active = 0
        lock = threading.Lock()

        def run(job):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.02)
            with lock:
                active -= 1
            return IssueJobResult(job, 0, "ok", 0.02)

        run_issue_jobs(jobs, workers=2, run_job_fn=run)

        self.assertLessEqual(max_active, 2)


if __name__ == "__main__":
    unittest.main()
