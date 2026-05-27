import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from import_repolens_results import (  # noqa: E402
    RepoLensFinding,
    build_issue_body,
    collect_findings,
    existing_repolens_keys,
    import_findings,
    main,
    parse_report_file,
)


class FakeClient:
    def __init__(self, open_issues=None):
        self.open_issues = open_issues or []
        self.labels = []
        self.created = []

    def list_open_issues(self, repo):
        return self.open_issues

    def ensure_label(self, repo, name):
        self.labels.append((repo, name))

    def create_issue(self, repo, title, body, labels):
        self.created.append((repo, title, body, labels))
        return f"https://github.test/{repo}/issues/{len(self.created)}"


class ImportRepoLensResultsTests(unittest.TestCase):
    def test_parse_heading_finding_maps_severity_domain_and_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report = Path(tmpdir) / "security.md"
            report.write_text(
                """# RepoLens Security

### High: Hardcoded API token in config
Files: `config/settings.py`, `scripts/deploy.py`
Evidence: token value is committed in a default config file.
Recommendation: read it from the environment.
""",
                encoding="utf-8",
            )

            findings = parse_report_file(report)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].title, "Hardcoded API token in config")
        self.assertEqual(findings[0].severity, "high")
        self.assertEqual(findings[0].domain, "security")
        self.assertEqual(findings[0].affected_files, ("config/settings.py", "scripts/deploy.py"))
        self.assertIn("severity:high", findings[0].labels)
        self.assertIn("security", findings[0].labels)

    def test_parse_bullet_finding(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            report = Path(tmpdir) / "performance-report.md"
            report.write_text(
                """# RepoLens

- [Medium] Performance: slow repository scan
  Files: `scripts/analyze_repos.py`
  Evidence: repeated API calls are performed without caching.
""",
                encoding="utf-8",
            )

            findings = collect_findings(Path(tmpdir))

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].title, "slow repository scan")
        self.assertEqual(findings[0].severity, "medium")
        self.assertEqual(findings[0].domain, "performance")

    def test_build_issue_body_contains_marker_source_and_affected_files(self):
        finding = RepoLensFinding(
            title="Hardcoded token",
            severity="high",
            domain="security",
            source_file=Path("/tmp/reports/repolens/security.md"),
            affected_files=("config/settings.py",),
            evidence="Evidence: token is present.",
        )

        body = build_issue_body(finding, Path("/tmp/reports/repolens"))

        self.assertIn(f"<!-- repolens:{finding.key} -->", body)
        self.assertIn("`security.md`", body)
        self.assertIn("`config/settings.py`", body)
        self.assertIn("Domain/Lens", body)

    def test_import_apply_skips_existing_marker_and_title(self):
        finding = RepoLensFinding(
            title="Hardcoded token",
            severity="high",
            domain="security",
            source_file=Path("reports/repolens/security.md"),
            affected_files=(),
            evidence="Evidence",
        )
        client = FakeClient(
            [
                {
                    "title": "Different title",
                    "body": f"<!-- repolens:{finding.key} -->",
                }
            ]
        )

        with contextlib.redirect_stdout(io.StringIO()):
            created, skipped = import_findings([finding], "demo", Path("reports/repolens"), True, client)

        self.assertEqual(created, 0)
        self.assertEqual(skipped, 1)
        self.assertEqual(client.created, [])

    def test_import_apply_creates_labels_and_issue(self):
        finding = RepoLensFinding(
            title="Slow query",
            severity="medium",
            domain="performance",
            source_file=Path("reports/repolens/perf.md"),
            affected_files=("src/db.py",),
            evidence="Evidence",
        )
        client = FakeClient()

        with contextlib.redirect_stdout(io.StringIO()):
            created, skipped = import_findings([finding], "demo", Path("reports/repolens"), True, client)

        self.assertEqual((created, skipped), (1, 0))
        self.assertIn(("demo", "repolens"), client.labels)
        self.assertIn(("demo", "severity:medium"), client.labels)
        self.assertIn(("demo", "performance"), client.labels)
        self.assertEqual(client.created[0][1], "[RepoLens] Medium: Slow query")

    def test_existing_repolens_keys_reads_markers(self):
        keys = existing_repolens_keys(
            [
                {"body": "<!-- repolens:0123456789abcdef -->"},
                {"body": "no marker"},
            ]
        )

        self.assertEqual(keys, {"0123456789abcdef"})

    def test_main_requires_apply_and_confirm_create_together(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    main(["--report-dir", tmpdir, "--repo", "demo", "--apply"])

        self.assertNotEqual(raised.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
