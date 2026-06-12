import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from solver_supervisor import (  # noqa: E402
    classify_run_health,
    filter_active_runs,
    format_run_line,
    format_dry_run_stop,
    process_tree,
    read_supervisor_runs,
    run_stop_dry_run,
    select_runs,
)


class SolverSupervisorStatusTests(unittest.TestCase):
    def write_run(self, runs_dir: Path, name: str, summary: str = "", metadata=None, health=None) -> Path:
        run_dir = runs_dir / name
        run_dir.mkdir(parents=True)
        if summary:
            (run_dir / "summary.txt").write_text(summary, encoding="utf-8")
        if metadata is not None:
            (run_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        if health is not None:
            (run_dir / "health.json").write_text(json.dumps(health), encoding="utf-8")
        return run_dir

    def test_classifies_recent_running_run_as_healthy(self):
        now = datetime(2026, 6, 5, 17, 0, 0)
        health, reason = classify_run_health(
            "started",
            "worker_running",
            now - timedelta(seconds=30),
            now,
            stale_seconds=120,
        )
        self.assertEqual(health, "healthy")
        self.assertIn("worker_running", reason)

    def test_classifies_stale_running_run(self):
        now = datetime(2026, 6, 5, 17, 0, 0)
        health, reason = classify_run_health(
            "started",
            "worker_running",
            now - timedelta(minutes=20),
            now,
            stale_seconds=300,
        )
        self.assertEqual(health, "stale")
        self.assertIn("1200s", reason)

    def test_terminal_status_is_finished_even_with_old_timestamp(self):
        now = datetime(2026, 6, 5, 17, 0, 0)
        health, reason = classify_run_health(
            "pr_created",
            "creating_pr",
            now - timedelta(days=1),
            now,
            stale_seconds=60,
        )
        self.assertEqual(health, "finished")
        self.assertEqual(reason, "terminal status")

    def test_warning_pr_status_is_terminal(self):
        now = datetime(2026, 6, 5, 17, 0, 0)
        health, reason = classify_run_health(
            "pr_created_with_warning",
            "",
            now - timedelta(days=1),
            now,
            stale_seconds=60,
        )
        self.assertEqual(health, "finished")
        self.assertEqual(reason, "terminal status")

    def test_read_supervisor_runs_merges_summary_metadata_and_health(self):
        now = datetime(2026, 6, 5, 17, 0, 0)
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir)
            self.write_run(
                runs_dir,
                "20260605-165900-demo-issue-7",
                summary="""status: started
repo: demo
issue: 7
branch: ai/fix-issue-7
model: opencode
""",
                health={
                    "status": "running",
                    "phase": "worker_running",
                    "last_activity_at": "2026-06-05T16:59:30",
                    "last_report_update_at": "2026-06-05T16:59:31",
                    "output_tail": "still working",
                    "process": {"worker_pid": 12345},
                },
            )

            runs = read_supervisor_runs(runs_dir, now=now, stale_seconds=120)

        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].repo, "demo")
        self.assertEqual(runs[0].issue, "7")
        self.assertEqual(runs[0].phase, "worker_running")
        self.assertEqual(runs[0].worker_pid, "12345")
        self.assertEqual(runs[0].health_status, "healthy")
        self.assertEqual(runs[0].output_tail, "still working")

    def test_filter_active_runs_excludes_finished_runs(self):
        now = datetime(2026, 6, 5, 17, 0, 0)
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir)
            self.write_run(
                runs_dir,
                "running-run",
                summary="status: started\nrepo: demo\nissue: 1\n",
                health={
                    "status": "running",
                    "phase": "worker_running",
                    "last_report_update_at": "2026-06-05T16:59:55",
                },
            )
            self.write_run(
                runs_dir,
                "finished-run",
                summary="status: pr_created\nrepo: demo\nissue: 2\n",
                metadata={
                    "status": "pr_created",
                    "repo": "demo",
                    "issue_number": 2,
                    "last_report_update_at": "2026-06-05T16:00:00",
                },
            )

            active = filter_active_runs(read_supervisor_runs(runs_dir, now=now, stale_seconds=120))

        self.assertEqual([run.issue for run in active], ["1"])

    def test_format_run_line_contains_key_fields(self):
        now = datetime(2026, 6, 5, 17, 0, 0)
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir)
            self.write_run(
                runs_dir,
                "demo-run",
                summary="status: started\nrepo: demo\nissue: 9\nmodel: opencode\n",
                health={"last_report_update_at": "2026-06-05T16:59:00", "phase": "clone"},
            )
            run = read_supervisor_runs(runs_dir, now=now, stale_seconds=120)[0]

        line = format_run_line(run)
        self.assertIn("demo", line)
        self.assertIn("#9", line)
        self.assertIn("clone", line)

    def test_select_runs_filters_by_repo_and_issue(self):
        now = datetime(2026, 6, 5, 17, 0, 0)
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir)
            self.write_run(
                runs_dir,
                "run-1",
                summary="status: started\nrepo: demo\nissue: 9\n",
                health={"last_report_update_at": "2026-06-05T16:59:00"},
            )
            self.write_run(
                runs_dir,
                "run-2",
                summary="status: started\nrepo: other\nissue: 9\n",
                health={"last_report_update_at": "2026-06-05T16:59:00"},
            )
            runs = read_supervisor_runs(runs_dir, now=now, stale_seconds=120)

        selected = select_runs(runs, repo="demo", issue="9")

        self.assertEqual([run.run_id for run in selected], ["run-1"])

    def test_process_tree_collects_children_without_signals(self):
        def fake_children(pid):
            return {
                10: [11, 12],
                11: [13],
                12: [],
                13: [],
            }.get(pid, [])

        with patch("solver_supervisor.direct_child_pids", side_effect=fake_children):
            self.assertEqual(process_tree([10]), [10, 11, 12, 13])

    def test_format_dry_run_stop_includes_process_tree(self):
        now = datetime(2026, 6, 5, 17, 0, 0)
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir)
            self.write_run(
                runs_dir,
                "run-1",
                summary="status: started\nrepo: demo\nissue: 9\n",
                health={
                    "last_report_update_at": "2026-06-05T16:59:00",
                    "process": {"runner_pid": 10, "worker_pid": 20},
                },
            )
            run = read_supervisor_runs(runs_dir, now=now, stale_seconds=120)[0]

        with patch("solver_supervisor.process_tree", return_value=[10, 20, 21]):
            lines = format_dry_run_stop(run)

        text = "\n".join(lines)
        self.assertIn("DRY-RUN stop target: run-1", text)
        self.assertIn("worker_pid: 20", text)
        self.assertIn("process_tree: 10, 20, 21", text)
        self.assertIn("no signal sent", text)

    def test_stop_without_dry_run_is_rejected(self):
        class Args:
            runs_dir = ""
            stale_seconds = 120
            run_id = "run-1"
            repo = None
            issue = None
            worker_pid = None
            dry_run = False

        now = datetime(2026, 6, 5, 17, 0, 0)
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir)
            self.write_run(
                runs_dir,
                "run-1",
                summary="status: started\nrepo: demo\nissue: 9\n",
                health={"last_report_update_at": "2026-06-05T16:59:00"},
            )
            args = Args()
            args.runs_dir = str(runs_dir)

            with patch("solver_supervisor.datetime") as fake_datetime, \
                 patch("solver_supervisor.print_warn"):
                fake_datetime.now.return_value = now
                fake_datetime.strptime = datetime.strptime
                result = run_stop_dry_run(args)

        self.assertEqual(result, 2)


if __name__ == "__main__":
    unittest.main()
