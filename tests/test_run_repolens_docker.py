import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_repolens_docker.sh"


class RunRepoLensDockerTests(unittest.TestCase):
    def test_help_documents_safe_defaults(self):
        result = subprocess.run(
            ["bash", str(SCRIPT), "--help"],
            check=True,
            text=True,
            capture_output=True,
        )

        self.assertIn("read-only at /project", result.stdout)
        self.assertIn("writable at /reports", result.stdout)
        self.assertIn("No .env file or GitHub write token", result.stdout)

    def test_script_uses_constrained_mounts_and_network_default(self):
        text = SCRIPT.read_text(encoding="utf-8")

        self.assertIn('network="${REPOLENS_NETWORK:-none}"', text)
        self.assertIn('--network "$network"', text)
        self.assertIn('--user "$(id -u):$(id -g)"', text)
        self.assertIn('-v "$project_dir:/project:ro"', text)
        self.assertIn('-v "$report_dir:/reports"', text)
        self.assertIn("--cpus", text)
        self.assertIn("--memory", text)
        self.assertNotIn("--env-file", text)
        self.assertNotIn("GITHUB_TOKEN", text)


if __name__ == "__main__":
    unittest.main()
