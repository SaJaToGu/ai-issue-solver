import subprocess
import unittest
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


if __name__ == "__main__":
    unittest.main()
