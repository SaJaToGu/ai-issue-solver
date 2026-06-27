import subprocess
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import benchmark_free_models


class BenchmarkFreeModelsTests(unittest.TestCase):
    def test_run_one_uses_benchmark_skip_pr_flags(self):
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="pr_skipped\n",
            stderr="",
        )
        with patch("scripts.benchmark_free_models.subprocess.run", return_value=completed) as run_mock:
            benchmark_free_models.run_one(
                390,
                "openrouter_direct",
                "qwen/qwen3-coder:free",
                1,
                1,
            )

        cmd = run_mock.call_args.args[0]
        self.assertIn("--benchmark", cmd)
        self.assertIn("--skip-pr", cmd)
        self.assertIn("--issue", cmd)
        # issue_number 390 must appear in the cmd list
        self.assertIn("390", cmd)

    def test_default_model_specs_uses_dynamic_discovery(self):
        with patch(
            "scripts.model_catalog.fetch_openrouter_free_models",
            return_value=SimpleNamespace(
                models=("qwen/qwen3-coder:free",),
                source="live",
            ),
        ), patch(
            "scripts.model_catalog.fetch_opencode_free_models",
            return_value=SimpleNamespace(
                models=("opencode/deepseek-v4-flash-free",),
                source="cache",
            ),
        ):
            models, source = benchmark_free_models.default_model_specs()

        self.assertEqual(
            models,
            [
                ("openrouter_direct", "qwen/qwen3-coder:free"),
                ("opencode", "opencode/deepseek-v4-flash-free"),
            ],
        )
        self.assertEqual(source, "openrouter:live/opencode:cache")

    def test_explicit_models_bypass_dynamic_discovery(self):
        with patch("scripts.benchmark_free_models.default_model_specs") as default_mock:
            models = benchmark_free_models.explicit_model_specs(
                "openrouter_direct:missing/model:free,opencode:opencode/foo-free"
            )

        default_mock.assert_not_called()
        self.assertEqual(
            models,
            [
                ("openrouter_direct", "missing/model:free"),
                ("opencode", "opencode/foo-free"),
            ],
        )


def _write_summary(run_report: Path, **fields: object) -> None:
    """Write a minimal but valid ``summary.txt`` for tests."""
    lines = [f"{key}: {value}" for key, value in fields.items()]
    run_report.mkdir(parents=True, exist_ok=True)
    (run_report / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


class ClassifyFromRunReportTests(unittest.TestCase):
    """Each new canonical classification class — driven by summary.txt fields."""

    def test_worker_exit_code_zero_with_changes_pr_created(self):
        with self._temp_run_report(
            worker_exit_code="0",
            run_outcome_has_changes="True",
            status="pr_created",
        ) as run_report:
            self.assertEqual(
                benchmark_free_models.classify(
                    "openrouter_direct",
                    "openai/gpt-4o",
                    0,
                    "PR erstellt\n",
                    run_report=run_report,
                ),
                "success_pr_created",
            )

    def test_worker_exit_code_zero_with_changes_pr_skipped(self):
        with self._temp_run_report(
            worker_exit_code="0",
            run_outcome_has_changes="True",
            status="pr_skipped",
        ) as run_report:
            self.assertEqual(
                benchmark_free_models.classify(
                    "openrouter_direct",
                    "openai/gpt-4o",
                    0,
                    "PR skipped",
                    run_report=run_report,
                ),
                "success_pr_skipped",
            )

    def test_worker_exit_code_zero_no_changes_returns_no_changes(self):
        """The §67 bugfix: rc=0 + has_changes=False is noop, not success."""
        with self._temp_run_report(
            worker_exit_code="0",
            run_outcome_has_changes="False",
            status="no_changes",
        ) as run_report:
            self.assertEqual(
                benchmark_free_models.classify(
                    "openrouter_direct",
                    "openai/gpt-4o",
                    0,
                    "Keine Patches",
                    run_report=run_report,
                ),
                "no_changes",
            )

    def test_worker_exit_code_one_returns_model_failure(self):
        with self._temp_run_report(
            worker_exit_code="1",
            run_outcome_has_changes="False",
            status="nonzero_without_changes",
        ) as run_report:
            self.assertEqual(
                benchmark_free_models.classify(
                    "openrouter_direct",
                    "openai/gpt-4o",
                    1,
                    "API-Fehler: 500",
                    run_report=run_report,
                ),
                "model_failure_rc1",
            )

    def test_worker_exit_code_two_returns_empty_response(self):
        with self._temp_run_report(
            worker_exit_code="2",
            run_outcome_has_changes="False",
            status="nonzero_without_changes",
        ) as run_report:
            self.assertEqual(
                benchmark_free_models.classify(
                    "openrouter_direct",
                    "openai/gpt-4o",
                    2,
                    "Modellantwort war leer",
                    run_report=run_report,
                ),
                "empty_response_rc2",
            )

    def test_worker_exit_code_five_returns_patch_validation_failed(self):
        with self._temp_run_report(
            worker_exit_code="5",
            run_outcome_has_changes="False",
            status="validation_failed",
        ) as run_report:
            self.assertEqual(
                benchmark_free_models.classify(
                    "openrouter_direct",
                    "openai/gpt-4o",
                    5,
                    "VALIDATION-FAILED",
                    run_report=run_report,
                ),
                "patch_validation_failed_rc5",
            )

    def test_worker_exit_code_six_returns_partial_patch_failure(self):
        with self._temp_run_report(
            worker_exit_code="6",
            run_outcome_has_changes="False",
            status="nonzero_without_changes",
        ) as run_report:
            self.assertEqual(
                benchmark_free_models.classify(
                    "openrouter_direct",
                    "openai/gpt-4o",
                    6,
                    "partial patch",
                    run_report=run_report,
                ),
                "partial_patch_failure_rc6",
            )

    def test_429_in_log_text_returns_openrouter_429(self):
        with self._temp_run_report(
            worker_exit_code="1",
            run_outcome_has_changes="False",
            status="nonzero_without_changes",
        ) as run_report:
            self.assertEqual(
                benchmark_free_models.classify(
                    "openrouter_direct",
                    "openai/gpt-4o",
                    1,
                    "429 Too Many Requests",
                    run_report=run_report,
                ),
                "openrouter_429",
            )

    def test_missing_run_report_falls_back_to_log_text(self):
        """When summary.txt does not exist, classify() uses log-text heuristics."""
        self.assertEqual(
            benchmark_free_models.classify(
                "openrouter_direct",
                "openai/gpt-4o",
                1,
                "VALIDATION-FAILED: Reject-Artefakte",
                run_report=None,
            ),
            "patch_validation_failed_rc5",
        )

    def test_missing_run_report_and_rc_zero_returns_no_changes(self):
        """Legacy ``success_no_pr`` fall-through is gone — default is no_changes."""
        self.assertEqual(
            benchmark_free_models.classify(
                "openrouter_direct",
                "openai/gpt-4o",
                0,
                "",
                run_report=None,
            ),
            "no_changes",
        )

    def _temp_run_report(self, **fields: object):
        """Context manager that yields a temp run-report dir with summary.txt."""
        import tempfile

        @staticmethod
        def _make_cm():
            tmp = tempfile.TemporaryDirectory()
            run_report = Path(tmp.name) / "20260627-060000-000000-ai-issue-solver-issue-464"
            _write_summary(run_report, **fields)

            class _CM:
                def __enter__(self_inner):
                    return run_report

                def __exit__(self_inner, exc_type, exc, tb):
                    tmp.cleanup()
                    return False

            return _CM()

        return _make_cm()


class FindRunReportTests(unittest.TestCase):
    def test_find_run_report_matches_in_window(self):
        import os
        import tempfile
        from datetime import timedelta

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            started = datetime.now(timezone.utc)
            finished = started  # placeholder; window is what matters

            # Build three candidate dirs with explicit mtimes so the window
            # match is deterministic regardless of when the test runs.
            old = root / "20260627-055900-000000-ai-issue-solver-issue-464"
            old.mkdir()
            (old / "summary.txt").write_text("worker_exit_code: 0\n", encoding="utf-8")
            old_ts = (started - timedelta(seconds=600)).timestamp()
            os.utime(old, (old_ts, old_ts))

            target = root / "20260627-060002-000000-ai-issue-solver-issue-464"
            target.mkdir()
            (target / "summary.txt").write_text("worker_exit_code: 0\n", encoding="utf-8")
            target_ts = (started + timedelta(seconds=2)).timestamp()
            os.utime(target, (target_ts, target_ts))

            other = root / "20260627-060002-000000-ai-issue-solver-issue-999"
            other.mkdir()

            with patch.object(benchmark_free_models, "RUN_REPORTS_ROOT", root):
                found = benchmark_free_models._find_run_report(464, started, finished)

            self.assertEqual(found, target)

    def test_find_run_report_returns_none_when_no_match(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            started = datetime.now(timezone.utc)
            finished = started
            with patch.object(benchmark_free_models, "RUN_REPORTS_ROOT", root):
                self.assertIsNone(
                    benchmark_free_models._find_run_report(464, started, finished)
                )


if __name__ == "__main__":
    unittest.main()
