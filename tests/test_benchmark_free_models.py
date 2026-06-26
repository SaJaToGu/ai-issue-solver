import subprocess
import unittest
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


if __name__ == "__main__":
    unittest.main()
