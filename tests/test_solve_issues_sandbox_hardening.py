#!/usr/bin/env python3
"""
Tests für die Codex-Sandbox-Härtung (Issue #217).

Deckt die schmale Klassifizierung von Sandbox-/Git-Fehlern und den
Codex-Environment-Preflight ab. Der Schwerpunkt liegt auf
diagnostisch eng abgegrenzten Empfehlungen.
"""

import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from solve_issues import (  # noqa: E402
    CodexEnvPreflight,
    SandboxFailureDiagnosis,
    classify_sandbox_failure,
    format_escalation_recommendation,
    print_codex_environment_preflight,
    recommend_escalation_prefix,
    run_codex_environment_preflight,
)


class SandboxNetworkClassificationTests(unittest.TestCase):
    """Klassifizierung von DNS-/Netzwerk-Fehlern in der Codex-Sandbox."""

    def test_dns_failure_is_classified_as_network(self):
        diagnosis = classify_sandbox_failure(
            "fatal: unable to access 'https://github.com/x/y.git/': "
            "Could not resolve host: github.com"
        )
        self.assertEqual(diagnosis.kind, "network")
        self.assertEqual(diagnosis.matched_pattern, "Could not resolve host")
        self.assertIn("Sandbox-Block: DNS/Netzwerk", diagnosis.hint)

    def test_temporary_name_resolution_failure(self):
        diagnosis = classify_sandbox_failure(
            "Temporary failure in name resolution"
        )
        self.assertEqual(diagnosis.kind, "network")
        self.assertEqual(diagnosis.matched_pattern, "Temporary failure in name resolution")

    def test_connection_refused_is_network(self):
        diagnosis = classify_sandbox_failure(
            "Failed to connect to api.github.com port 443: Connection refused"
        )
        self.assertEqual(diagnosis.kind, "network")
        self.assertEqual(diagnosis.matched_pattern, "Failed to connect to")

    def test_tls_error_is_network(self):
        diagnosis = classify_sandbox_failure(
            "ssl3_get_record: wrong version number"
        )
        self.assertEqual(diagnosis.kind, "network")
        self.assertEqual(diagnosis.matched_pattern, "ssl3_get_record: wrong version number")

    def test_getaddrinfo_is_network(self):
        diagnosis = classify_sandbox_failure("getaddrinfo failed")
        self.assertEqual(diagnosis.kind, "network")
        self.assertEqual(diagnosis.matched_pattern, "getaddrinfo failed")

    def test_network_recommendation_mentions_danger_full_access(self):
        diagnosis = classify_sandbox_failure("Could not resolve host: api.github.com")
        # Bewusst schmal: nur die danger-full-access-Empfehlung, keine breite Allowlist.
        self.assertIn("danger-full-access", diagnosis.hint)


class GitWritePermissionClassificationTests(unittest.TestCase):
    """Klassifizierung von .git-Schreibrechte-Fehlern in der Codex-Sandbox."""

    def test_fetch_head_failure_is_git_write(self):
        diagnosis = classify_sandbox_failure(
            "error: unable to write FETCH_HEAD"
        )
        self.assertEqual(diagnosis.kind, "git_write")
        self.assertEqual(
            diagnosis.matched_pattern,
            ".git/FETCH_HEAD konnte nicht geschrieben werden",
        )
        self.assertIn("FETCH_HEAD", diagnosis.hint)
        self.assertIn("danger-full-access", diagnosis.hint)

    def test_index_lock_is_git_write(self):
        diagnosis = classify_sandbox_failure(
            "fatal: Unable to create .git/index.lock: File exists"
        )
        self.assertEqual(diagnosis.kind, "git_write")
        self.assertEqual(
            diagnosis.matched_pattern,
            "Bestehende .git/index.lock blockiert den Index-Update",
        )
        self.assertIn("index.lock", diagnosis.hint.lower())
        self.assertIn("rm -f .git/index.lock", diagnosis.hint)

    def test_permission_denied_in_git_is_git_write(self):
        diagnosis = classify_sandbox_failure(
            "error: could not write to .git/HEAD: Permission denied"
        )
        self.assertEqual(diagnosis.kind, "git_write")
        self.assertEqual(
            diagnosis.matched_pattern,
            "Fehlende Schreibrechte im .git/-Verzeichnis",
        )
        self.assertIn("Schreibrechte", diagnosis.hint)

    def test_read_only_filesystem_is_git_write(self):
        diagnosis = classify_sandbox_failure(
            "error: Read-only file system when writing to .git/config"
        )
        self.assertEqual(diagnosis.kind, "git_write")
        self.assertEqual(
            diagnosis.matched_pattern,
            ".git/-Verzeichnis ist schreibgeschützt gemountet",
        )
        self.assertIn("schreibgeschützt", diagnosis.hint)

    def test_operation_not_permitted_is_git_write(self):
        diagnosis = classify_sandbox_failure(
            "git: .git/objects/abc: Operation not permitted"
        )
        self.assertEqual(diagnosis.kind, "git_write")
        self.assertEqual(
            diagnosis.matched_pattern,
            "Sandbox blockiert Schreibzugriff auf .git/",
        )
        self.assertIn("danger-full-access", diagnosis.hint)

    def test_unknown_text_is_unknown(self):
        diagnosis = classify_sandbox_failure("Some completely unrelated error text")
        self.assertEqual(diagnosis.kind, "unknown")
        self.assertIsNone(diagnosis.matched_pattern)
        self.assertIn("Fehlerursache unbekannt", diagnosis.hint)

    def test_empty_text_is_unknown(self):
        diagnosis = classify_sandbox_failure("")
        self.assertEqual(diagnosis.kind, "unknown")
        self.assertIsNone(diagnosis.matched_pattern)

    def test_network_takes_precedence_over_git_write(self):
        # Wenn sowohl DNS- als auch Git-Write-Hinweise vorkommen,
        # wird zuerst Netzwerk klassifiziert (häufigerer Auslöser).
        diagnosis = classify_sandbox_failure(
            "Could not resolve host: github.com while writing FETCH_HEAD"
        )
        self.assertEqual(diagnosis.kind, "network")


class FormatEscalationRecommendationTests(unittest.TestCase):
    """Die formatierte Empfehlung bleibt schmal und task-spezifisch."""

    def test_network_format_mentions_sandbox_block(self):
        diagnosis = classify_sandbox_failure("Could not resolve host")
        text = format_escalation_recommendation(diagnosis)
        self.assertTrue(text.startswith("DNS/Netzwerk erkannt"))
        self.assertIn("Sandbox-Block", text)

    def test_git_write_format_mentions_pattern(self):
        diagnosis = classify_sandbox_failure("error: unable to write FETCH_HEAD")
        text = format_escalation_recommendation(diagnosis)
        self.assertTrue(text.startswith("Git-Schreibrechte erkannt"))
        self.assertIn("FETCH_HEAD", text)

    def test_unknown_format_returns_plain_hint(self):
        diagnosis = SandboxFailureDiagnosis("unknown", None, "irgendwas")
        self.assertEqual(format_escalation_recommendation(diagnosis), "irgendwas")


class RecommendEscalationPrefixTests(unittest.TestCase):
    """Schmale Empfehlungen, nur fuer ausgewaehlte Befehle."""

    def test_pull_ff_only_recommends_pull(self):
        self.assertEqual(
            recommend_escalation_prefix("git pull --ff-only"),
            "git pull --ff-only",
        )

    def test_git_switch_recommends_switch(self):
        self.assertEqual(
            recommend_escalation_prefix("git switch main"),
            "git switch",
        )

    def test_gh_pr_checks_recommends_pr_checks(self):
        self.assertEqual(
            recommend_escalation_prefix("gh pr checks 42"),
            "gh pr checks",
        )

    def test_gh_run_view_recommends_run_view(self):
        self.assertEqual(
            recommend_escalation_prefix("gh run view 12345"),
            "gh run view",
        )

    def test_unknown_command_returns_none(self):
        # Bewusst keine breite Allowlist — unbekannte Befehle bleiben ohne Empfehlung.
        self.assertIsNone(recommend_escalation_prefix("rm -rf /tmp/ai-solver-xyz"))
        self.assertIsNone(recommend_escalation_prefix("kubectl apply -f x.yaml"))
        self.assertIsNone(recommend_escalation_prefix("docker run --rm -it alpine"))
        self.assertIsNone(recommend_escalation_prefix(""))
        self.assertIsNone(recommend_escalation_prefix("   "))

    def test_partial_match_for_unsupported_command_returns_none(self):
        # "git pull" ohne --ff-only wird NICHT empfohlen, um task-spezifisch zu bleiben.
        self.assertIsNone(recommend_escalation_prefix("git pull --rebase"))
        # "git checkout" (alt) ist nicht enthalten, nur "git switch".
        self.assertIsNone(recommend_escalation_prefix("git checkout main"))


class CodexEnvironmentPreflightTests(unittest.TestCase):
    """Codex-Environment-Preflight: gh + Python-requests, isoliert auswertbar."""

    def test_preflight_uses_gh_and_requests_runner(self):
        config = {"GITHUB_TOKEN": "ghp_dummy"}

        def fake_requests_runner(token, timeout=8.0):
            return True, "octocat", None

        # `gh` ist auf den meisten Testumgebungen nicht installiert — das ist ok.
        with patch(
            "solve_issues._run_gh_api_user_probe",
            return_value=(False, True, "gh nicht im PATH"),
        ):
            preflight = run_codex_environment_preflight(
                config, runner=fake_requests_runner
            )

        self.assertTrue(preflight.gh_skipped)
        self.assertFalse(preflight.gh_ok)
        self.assertTrue(preflight.requests_ok)
        self.assertEqual(preflight.api_user, "octocat")
        self.assertIsNone(preflight.error)

    def test_preflight_reports_dns_failure(self):
        config = {"GITHUB_TOKEN": "ghp_dummy"}

        def fake_requests_runner(token, timeout=8.0):
            return False, None, "Could not resolve host: api.github.com"

        with patch(
            "solve_issues._run_gh_api_user_probe",
            return_value=(False, False, "gh exit 1"),
        ):
            preflight = run_codex_environment_preflight(
                config, runner=fake_requests_runner
            )

        self.assertFalse(preflight.requests_ok)
        self.assertIn("Could not resolve host", preflight.error or "")

        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            print_codex_environment_preflight(preflight, user="alice")

        output = printed.getvalue()
        self.assertIn("requests /user fehlgeschlagen", output)
        self.assertIn("Could not resolve host", output)
        # DNS-spezifischer Eskalations-Hinweis wird mit ausgegeben.
        self.assertIn("Eskalations-Hinweis", output)

    def test_preflight_reports_successful_gh_and_requests(self):
        config = {"GITHUB_TOKEN": "ghp_dummy"}

        def fake_requests_runner(token, timeout=8.0):
            return True, "octocat", None

        with patch(
            "solve_issues._run_gh_api_user_probe",
            return_value=(True, False, None),
        ):
            preflight = run_codex_environment_preflight(
                config, runner=fake_requests_runner
            )

        self.assertTrue(preflight.gh_ok)
        self.assertFalse(preflight.gh_skipped)
        self.assertTrue(preflight.requests_ok)
        self.assertEqual(preflight.api_user, "octocat")

        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            print_codex_environment_preflight(preflight, user="alice")

        output = printed.getvalue()
        self.assertIn("gh api user erreichbar", output)
        self.assertIn("requests /user ok", output)
        self.assertIn("octocat", output)

    def test_preflight_uses_default_runner_without_token_validation(self):
        # Ohne GITHUB_TOKEN sollte der Preflight früh fehlschlagen,
        # nicht stillschweigend `requests is None` maskieren.
        # Der Fallback ``gh auth token`` wird deterministisch auf
        # ``FileNotFoundError`` gepatcht, damit der Test in jeder
        # Umgebung (CI, Developer-Maschine mit ``gh auth login``,
        # Mavis-Shell) gleich verhält.
        import unittest.mock as mock
        with mock.patch(
            "subprocess.run", side_effect=FileNotFoundError("gh not found")
        ):
            with self.assertRaises((SystemExit, Exception)):
                run_codex_environment_preflight({})


if __name__ == "__main__":
    unittest.main()
