import argparse
import json
import tempfile
from datetime import datetime
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
    create_queued_run_report,
    dedupe_issue_jobs,
    discover_issue_jobs,
    finalize_unclaimed_queued_report,
    run_issue_job_with_optional_fallback,
    run_issue_job,
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
            "fallback_model": None,
            "fallback_model_name": None,
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

    def test_build_worker_command_defers_codex_rate_limits_to_batch_runner(self):
        args = self.make_args(model="codex")

        cmd = build_worker_command(args, IssueJob("demo", 7), Path("scripts/solve_issues.py"))

        self.assertIn("--defer-codex-rate-limit", cmd)

    def test_build_worker_command_forwards_mistral_model_override(self):
        args = self.make_args(model="mistral", model_name="magistral-small-2509")

        cmd = build_worker_command(args, IssueJob("demo", 7), Path("scripts/solve_issues.py"))

        self.assertIn("--model", cmd)
        self.assertIn("mistral", cmd)
        self.assertIn("--model-name", cmd)
        self.assertIn("magistral-small-2509", cmd)
        self.assertNotIn("--defer-codex-rate-limit", cmd)

    def test_build_worker_command_forwards_opencode_model_override(self):
        args = self.make_args(model="opencode", model_name="mistral/mistral-small-2603")

        cmd = build_worker_command(args, IssueJob("demo", 7), Path("scripts/solve_issues.py"))

        self.assertIn("--model", cmd)
        self.assertIn("opencode", cmd)
        self.assertIn("--model-name", cmd)
        self.assertIn("mistral/mistral-small-2603", cmd)
        self.assertNotIn("--defer-codex-rate-limit", cmd)

    def test_build_worker_command_forwards_mistral_vibe(self):
        args = self.make_args(model="mistral-vibe")

        cmd = build_worker_command(args, IssueJob("demo", 7), Path("scripts/solve_issues.py"))

        self.assertIn("--model", cmd)
        self.assertIn("mistral-vibe", cmd)
        self.assertNotIn("--defer-codex-rate-limit", cmd)

    def test_build_worker_command_forwards_queued_report_dir(self):
        args = self.make_args(model="codex")

        cmd = build_worker_command(
            args,
            IssueJob("demo", 7),
            Path("scripts/solve_issues.py"),
            run_report_dir=Path("reports/runs/queued-demo"),
        )

        self.assertIn("--run-report-dir", cmd)
        self.assertIn("reports/runs/queued-demo", cmd)

    def test_build_worker_command_can_override_fallback_model(self):
        args = self.make_args(model="codex", model_name="")

        cmd = build_worker_command(
            args,
            IssueJob("demo", 7),
            Path("scripts/solve_issues.py"),
            model="mistral",
            model_name="magistral-medium-2509",
        )

        self.assertIn("--model", cmd)
        self.assertIn("mistral", cmd)
        self.assertIn("--model-name", cmd)
        self.assertIn("magistral-medium-2509", cmd)
        self.assertNotIn("--defer-codex-rate-limit", cmd)

    def test_create_queued_run_report_writes_lightweight_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report = create_queued_run_report(
                IssueJob("owner/demo", 7),
                "codex",
                base_branch="main",
                now_fn=lambda: datetime(2026, 5, 21, 9, 8, 7, 123456),
                reports_root=Path(tmpdir) / "runs",
            )
            summary = (report.path / "summary.txt").read_text(encoding="utf-8")
            metadata = json.loads((report.path / "metadata.json").read_text(encoding="utf-8"))

        self.assertEqual(report.path.name, "20260521-090807-123456-owner-demo-issue-7")
        self.assertIn("status: queued", summary)
        self.assertIn("repo: owner/demo", summary)
        self.assertIn("issue_number: 7", summary)
        self.assertIn("base_branch: main", summary)
        self.assertIn("model: codex", summary)
        self.assertIn("queued_at: 2026-05-21T09:08:07", summary)
        self.assertEqual(metadata["status"], "queued")
        self.assertEqual(metadata["base_branch"], "main")

    def test_codex_rate_limit_can_run_explicit_fallback_model(self):
        args = self.make_args(
            model="codex",
            fallback_model="mistral",
            fallback_model_name="magistral-medium-2509",
        )
        calls = []

        def run_job(job, cmd, project_root, env, **kwargs):
            calls.append(cmd)
            if len(calls) == 1:
                return IssueJobResult(
                    job,
                    1,
                    "Your rate limit will be reset on May 20, 2026, at 1:36 AM.\n",
                    1.0,
                )
            return IssueJobResult(job, 0, "fallback solved\n", 2.0)

        with tempfile.TemporaryDirectory() as tmpdir:
            report = create_queued_run_report(
                IssueJob("demo", 7),
                "codex",
                now_fn=lambda: datetime(2026, 5, 21, 9, 8, 7),
                reports_root=Path(tmpdir) / "runs",
            )

            result = run_issue_job_with_optional_fallback(
                IssueJob("demo", 7),
                args,
                Path("scripts/solve_issues.py"),
                Path(tmpdir),
                {},
                report,
                health_timeout_seconds=60,
                unhealthy_action="warn",
                detect_rate_limit_fn=lambda output: object() if "rate limit" in output.lower() else None,
                run_issue_job_fn=run_job,
            )
            summary = (report.path / "summary.txt").read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.fallback_from, "codex")
        self.assertEqual(result.actual_model, "mistral")
        self.assertIn("[batch-fallback]", result.output)
        self.assertEqual(len(calls), 2)
        self.assertIn("codex", calls[0])
        self.assertIn("mistral", calls[1])
        self.assertIn("magistral-medium-2509", calls[1])
        self.assertIn("fallback_from: codex", summary)
        self.assertIn("actual_model: mistral", summary)

    def test_fallback_does_not_run_for_non_rate_limit_failure(self):
        args = self.make_args(model="codex", fallback_model="mistral")
        calls = []

        def run_job(job, cmd, project_root, env, **kwargs):
            calls.append(cmd)
            return IssueJobResult(job, 1, "tests failed\n", 1.0)

        result = run_issue_job_with_optional_fallback(
            IssueJob("demo", 7),
            args,
            Path("scripts/solve_issues.py"),
            Path("."),
            {},
            None,
            health_timeout_seconds=60,
            unhealthy_action="warn",
            detect_rate_limit_fn=lambda output: None,
            run_issue_job_fn=run_job,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIsNone(result.fallback_from)
        self.assertEqual(len(calls), 1)

    def test_finalize_unclaimed_queued_report_replaces_stale_queue_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report = create_queued_run_report(
                IssueJob("demo", 7),
                "codex",
                base_branch="main",
                now_fn=lambda: datetime(2026, 5, 21, 9, 8, 7, 123456),
                reports_root=Path(tmpdir) / "runs",
            )

            changed = finalize_unclaimed_queued_report(
                report,
                IssueJobResult(IssueJob("demo", 7), 2, "worker failed\n", 0.1),
            )
            summary = (report.path / "summary.txt").read_text(encoding="utf-8")
            metadata = json.loads((report.path / "metadata.json").read_text(encoding="utf-8"))

        self.assertEqual(changed, report.path)
        self.assertIn("status: worker_finished", summary)
        self.assertIn("worker_exit_code: 2", summary)
        self.assertIn("output_tail:", summary)
        self.assertEqual(metadata["status"], "worker_finished")

    def test_finalize_unclaimed_queued_report_keeps_started_solver_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report = create_queued_run_report(
                IssueJob("demo", 7),
                "codex",
                reports_root=Path(tmpdir) / "runs",
            )
            (report.path / "summary.txt").write_text(
                "status: started\nrepo: demo\n",
                encoding="utf-8",
            )

            changed = finalize_unclaimed_queued_report(
                report,
                IssueJobResult(IssueJob("demo", 7), 2, "worker failed\n", 0.1),
            )
            summary = (report.path / "summary.txt").read_text(encoding="utf-8")

        self.assertIsNone(changed)
        self.assertEqual(summary, "status: started\nrepo: demo\n")


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

    def test_run_issue_jobs_marks_codex_rate_limited_job_delayed_without_retry(self):
        jobs = [IssueJob("demo", 1), IssueJob("demo", 2)]
        started = []

        def run(job):
            started.append(job.issue_number)
            if job.issue_number == 1:
                return IssueJobResult(
                    job,
                    1,
                    "You have reached the Codex message limit\n"
                    "Your rate limit will be reset on May 20, 2026, at 1:36 AM.\n",
                    0.0,
                )
            return IssueJobResult(job, 0, "ok", 0.0)

        results = run_issue_jobs(jobs, workers=1, run_job_fn=run)

        self.assertEqual(started, [1, 2])
        self.assertEqual(len(results), 2)
        delayed = [result for result in results if result.delayed]
        self.assertEqual(len(delayed), 1)
        self.assertEqual(delayed[0].job, IssueJob("demo", 1))
        self.assertEqual(delayed[0].delayed_until, datetime(2026, 5, 20, 1, 36))

    def test_run_issue_jobs_does_not_delay_successful_worker_with_rate_limit_text(self):
        jobs = [IssueJob("demo", 1)]

        def run(job):
            return IssueJobResult(
                job,
                0,
                "PR erstellt\nYour rate limit will be reset on May 20, 2026, at 1:36 AM.\n",
                0.0,
            )

        results = run_issue_jobs(jobs, workers=1, run_job_fn=run)

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].ok)
        self.assertFalse(results[0].delayed)

    def test_run_issue_jobs_requeues_rate_limited_job_after_other_available_jobs(self):
        jobs = [IssueJob("demo", 1), IssueJob("demo", 2)]
        started = []

        def run(job):
            started.append(job.issue_number)
            if job.issue_number == 1 and started.count(1) == 1:
                return IssueJobResult(
                    job,
                    1,
                    "Your rate limit will be reset on May 20, 2026, at 1:36 AM.\n",
                    0.0,
                )
            return IssueJobResult(job, 0, f"ok {job.issue_number}", 0.0)

        results = run_issue_jobs(
            jobs,
            workers=1,
            run_job_fn=run,
            requeue_delayed=True,
            now_fn=lambda: datetime(2026, 5, 20, 1, 36),
        )

        self.assertEqual(started, [1, 2, 1])
        self.assertEqual(len(results), 2)
        self.assertTrue(all(not result.delayed for result in results))
        self.assertEqual(sum(1 for result in results if result.ok), 2)

    def test_run_issue_jobs_stops_requeueing_after_retry_limit(self):
        jobs = [IssueJob("demo", 1)]
        started = []

        def run(job):
            started.append(job.issue_number)
            return IssueJobResult(
                job,
                1,
                "Your rate limit will be reset on May 20, 2026, at 1:36 AM.\n",
                0.0,
            )

        results = run_issue_jobs(
            jobs,
            workers=1,
            run_job_fn=run,
            requeue_delayed=True,
            max_rate_limit_requeues=1,
            now_fn=lambda: datetime(2026, 5, 20, 1, 36),
        )

        self.assertEqual(started, [1, 1])
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].delayed)
        self.assertEqual(results[0].job, IssueJob("demo", 1))

    def test_run_issue_jobs_sleeps_until_reset_when_only_delayed_jobs_remain(self):
        jobs = [IssueJob("demo", 1)]
        started = []
        sleeps = []

        def run(job):
            started.append(job.issue_number)
            if len(started) == 1:
                return IssueJobResult(
                    job,
                    1,
                    "Your rate limit will be reset on May 20, 2026, at 1:36 AM.\n",
                    0.0,
                )
            return IssueJobResult(job, 0, "ok", 0.0)

        results = run_issue_jobs(
            jobs,
            workers=1,
            run_job_fn=run,
            requeue_delayed=True,
            sleep_fn=sleeps.append,
            now_fn=lambda: datetime(2026, 5, 20, 1, 35, 30),
        )

        self.assertEqual(started, [1, 1])
        self.assertEqual(sleeps, [30.0])
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].ok)

    def test_run_issue_jobs_submits_ready_requeue_when_worker_slot_opens(self):
        jobs = [IssueJob("demo", 1), IssueJob("demo", 2)]
        started = []
        active = set()
        retried_while_second_job_active = False
        lock = threading.Lock()

        def run(job):
            nonlocal retried_while_second_job_active
            with lock:
                started.append(job.issue_number)
                active.add(job.issue_number)
                if job.issue_number == 1 and started.count(1) == 2 and 2 in active:
                    retried_while_second_job_active = True
            try:
                if job.issue_number == 1 and started.count(1) == 1:
                    return IssueJobResult(
                        job,
                        1,
                        "Your rate limit will be reset on May 20, 2026, at 1:36 AM.\n",
                        0.0,
                    )
                if job.issue_number == 2:
                    time.sleep(0.05)
                return IssueJobResult(job, 0, f"ok {job.issue_number}", 0.0)
            finally:
                with lock:
                    active.discard(job.issue_number)

        results = run_issue_jobs(
            jobs,
            workers=2,
            run_job_fn=run,
            requeue_delayed=True,
            now_fn=lambda: datetime(2026, 5, 20, 1, 36),
        )

        self.assertEqual(started.count(1), 2)
        self.assertTrue(retried_while_second_job_active)
        self.assertEqual(len(results), 2)
        self.assertEqual(sum(1 for result in results if result.ok), 2)

    def test_run_issue_job_stops_unhealthy_worker_without_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            worker = Path(tmpdir) / "worker.py"
            worker.write_text(
                "import time\n"
                "time.sleep(5)\n",
                encoding="utf-8",
            )

            result = run_issue_job(
                IssueJob("demo", 10),
                [sys.executable, str(worker)],
                Path(tmpdir),
                {},
                health_timeout_seconds=0.1,
                unhealthy_action="stop",
            )

        self.assertTrue(result.unhealthy)
        self.assertIn("keine Worker-Ausgabe", result.unhealthy_reason)
        self.assertIn("[batch-health] Unhealthy", result.output)

    def test_run_issue_jobs_requeues_unhealthy_job_once(self):
        jobs = [IssueJob("demo", 1)]
        started = []

        def run(job):
            started.append(job.issue_number)
            if len(started) == 1:
                return IssueJobResult(
                    job,
                    124,
                    "[batch-health] Unhealthy: keine Worker-Ausgabe\n",
                    0.0,
                    unhealthy=True,
                    unhealthy_reason="keine Worker-Ausgabe",
                )
            return IssueJobResult(job, 0, "ok", 0.0)

        results = run_issue_jobs(
            jobs,
            workers=1,
            run_job_fn=run,
            requeue_unhealthy=True,
            max_unhealthy_requeues=1,
        )

        self.assertEqual(started, [1, 1])
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].ok)


if __name__ == "__main__":
    unittest.main()
