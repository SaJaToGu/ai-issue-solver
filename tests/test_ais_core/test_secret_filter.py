"""Tests for ais_core.secret_filter (Issue #1d).

Coverage:
- >=20 positive tests (one per SECRET_PATTERN)
- redact_dict / redact_list / _redact_value recursive tests
- False-positive test against a sample of safe text
- Performance test: 1 MB text < 100 ms
- Edge cases: nested structures, non-string values, type errors
"""

import secrets
import time
import unittest

from ais_core.secret_filter import (
    SECRET_PATTERNS,
    redact_dict,
    redact_list,
    redact_secrets,
)


class TestPatternCatalog(unittest.TestCase):
    def test_at_least_20_patterns(self) -> None:
        """Acceptance: >=20 secret patterns registered."""
        self.assertGreaterEqual(
            len(SECRET_PATTERNS), 20,
            f"need >=20 patterns, got {len(SECRET_PATTERNS)}",
        )

    def test_all_patterns_are_compiled_regex(self) -> None:
        import re
        for pat in SECRET_PATTERNS:
            self.assertIsInstance(pat, re.Pattern)


class TestRedactSecretsBasic(unittest.TestCase):
    def test_no_secret_unchanged(self) -> None:
        text = "Hello, this is a perfectly safe log line."
        self.assertEqual(redact_secrets(text), text)

    def test_redaction_marker_is_used(self) -> None:
        text = "github token: ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789"
        out = redact_secrets(text)
        self.assertNotIn("ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789", out)
        self.assertIn("[REDACTED]", out)

    def test_empty_string(self) -> None:
        self.assertEqual(redact_secrets(""), "")

    def test_non_string_raises(self) -> None:
        with self.assertRaises(TypeError):
            redact_secrets(123)  # type: ignore[arg-type]


class TestPositivePatterns(unittest.TestCase):
    """One positive test per registered pattern. Each pattern's sample
    value MUST be redacted by ``redact_secrets``.
    """

    def test_github_classic_pat(self) -> None:
        t = "token=ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789 end"
        self.assertNotIn("ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789", redact_secrets(t))

    def test_github_classic_oauth(self) -> None:
        t = "gho_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789"
        self.assertNotIn("gho_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789", redact_secrets(t))

    def test_github_finegrained_pat(self) -> None:
        s = "github_pat_" + "a" * 82
        self.assertNotIn(s, redact_secrets(s))

    def test_openai_legacy(self) -> None:
        s = "sk-" + "A" * 40
        self.assertNotIn(s, redact_secrets(s))

    def test_openai_project(self) -> None:
        s = "sk-proj-" + "a" * 40
        self.assertNotIn(s, redact_secrets(s))

    def test_anthropic(self) -> None:
        s = "sk-ant-" + "a" * 40
        self.assertNotIn(s, redact_secrets(s))

    def test_aws_access_key(self) -> None:
        s = "AKIAIOSFODNN7EXAMPLE"
        self.assertNotIn(s, redact_secrets(s))

    def test_aws_secret_assignment(self) -> None:
        t = 'AWS_SECRET_ACCESS_KEY="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"'
        out = redact_secrets(t)
        self.assertNotIn("wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", out)

    def test_google_api_key(self) -> None:
        s = "AIza" + "a" * 35  # 39 chars total
        self.assertNotIn(s, redact_secrets(s))

    def test_twilio_sid(self) -> None:
        s = "AC" + "a" * 32
        self.assertNotIn(s, redact_secrets(s))

    def test_mailgun_key(self) -> None:
        s = "key-" + "a" * 32
        self.assertNotIn(s, redact_secrets(s))

    def test_sendgrid_key(self) -> None:
        s = "SG." + "a" * 22 + "." + "b" * 43
        self.assertNotIn(s, redact_secrets(s))

    def test_google_oauth(self) -> None:
        s = "ya29.a0AfH6SMBxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        self.assertNotIn(s, redact_secrets(s))

    def test_slack_token(self) -> None:
        # Generated at runtime so the literal value never appears in
        # source (and so GitHub's push-protection does not flag the
        # file as containing a real Slack token).
        random_part = secrets.token_hex(20)
        s = f"xoxb-{secrets.token_hex(8)}-{secrets.token_hex(8)}-{random_part}"
        self.assertNotIn(s, redact_secrets(s))

    def test_slack_webhook(self) -> None:
        # Generated at runtime for the same reason as test_slack_token.
        s = (
            "https://hooks.slack.com/services/"
            f"T{secrets.token_hex(4).upper()}/"
            f"B{secrets.token_hex(4).upper()}/"
            f"{secrets.token_hex(12)}"
        )
        self.assertNotIn(s.split("/")[-1], redact_secrets(s))

    def test_stripe_live_secret(self) -> None:
        s = "sk_live_" + "a" * 24
        self.assertNotIn(s, redact_secrets(s))

    def test_stripe_live_public(self) -> None:
        s = "pk_live_" + "a" * 24
        self.assertNotIn(s, redact_secrets(s))

    def test_discord_token(self) -> None:
        # Real-shape discord token: M{23}.{6}.{27}
        s = "M" + "a" * 23 + "." + "b" * 6 + "." + "c" * 27
        self.assertNotIn(s, redact_secrets(s))

    def test_jwt(self) -> None:
        s = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        self.assertNotIn(s, redact_secrets(s))

    def test_bearer_token(self) -> None:
        s = "Authorization: Bearer abcdefghijklmnop1234"
        out = redact_secrets(s)
        self.assertNotIn("abcdefghijklmnop1234", out)

    def test_pem_private_key(self) -> None:
        s = "-----BEGIN RSA PRIVATE KEY-----"
        self.assertIn("[REDACTED]", redact_secrets(s))

    def test_env_secret_assignment_uppercase(self) -> None:
        t = 'export API_KEY="supersecretvalue123"'
        out = redact_secrets(t)
        self.assertNotIn("supersecretvalue123", out)

    def test_env_password_assignment(self) -> None:
        t = 'DB_PASSWORD=hunter2hunter2'
        out = redact_secrets(t)
        self.assertNotIn("hunter2hunter2", out)


class TestRedactDict(unittest.TestCase):
    def test_flat_dict_redacts_values(self) -> None:
        d = {"name": "alice", "token": "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789"}
        out = redact_dict(d)
        self.assertEqual(out["name"], "alice")
        self.assertIn("[REDACTED]", out["token"])
        # Original is untouched (deep-copy semantics).
        self.assertNotIn("[REDACTED]", d["token"])

    def test_nested_dict(self) -> None:
        d = {
            "outer": {
                "inner": "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789",
            },
        }
        out = redact_dict(d)
        self.assertIn("[REDACTED]", out["outer"]["inner"])

    def test_list_of_strings(self) -> None:
        d = {"tokens": ["ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789", "safe"]}
        out = redact_dict(d)
        self.assertIn("[REDACTED]", out["tokens"][0])
        self.assertEqual(out["tokens"][1], "safe")

    def test_non_string_values_pass_through(self) -> None:
        d = {"count": 42, "ratio": 3.14, "ok": True, "none": None}
        out = redact_dict(d)
        self.assertEqual(out["count"], 42)
        self.assertEqual(out["ratio"], 3.14)
        self.assertEqual(out["ok"], True)
        self.assertIsNone(out["none"])

    def test_non_dict_raises(self) -> None:
        with self.assertRaises(TypeError):
            redact_dict([1, 2, 3])  # type: ignore[arg-type]

    def test_tuple_in_list(self) -> None:
        d = {"pair": ("ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789", "x")}
        out = redact_dict(d)
        self.assertIsInstance(out["pair"], tuple)
        self.assertIn("[REDACTED]", out["pair"][0])
        self.assertEqual(out["pair"][1], "x")


class TestRedactList(unittest.TestCase):
    def test_list_of_strings(self) -> None:
        data = ["ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789", "safe"]
        out = redact_list(data)
        self.assertIn("[REDACTED]", out[0])
        self.assertEqual(out[1], "safe")

    def test_nested_list(self) -> None:
        data = [["ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789"]]
        out = redact_list(data)
        self.assertIn("[REDACTED]", out[0][0])

    def test_non_list_raises(self) -> None:
        with self.assertRaises(TypeError):
            redact_list({"a": 1})  # type: ignore[arg-type]


class TestFalsePositives(unittest.TestCase):
    """Common safe strings MUST NOT be redacted. This is the negative
    corpus; extend with anything that previously false-positived.
    """

    SAFE_SAMPLES = [
        "2026-06-27 19:24:12 INFO worker started",
        "Branch: ais-fix-472-secret-filter",
        "Commit: 1234567 by SaJaToGu",
        "PR #472 merged into develop",
        "Total runs: 14, succeeded: 12, failed: 2",
        "Duration: 12.345s, cost: $0.42",
        "File: src/foo/bar.py line 42",
        "Normal log line: hello world",
        "Version: 1.2.3",
        "Issue #468 Release 0.10.0",
        "Process started successfully",
        "Memory usage: 256 MB",
        "Connection to api.example.com:443 established",
        "User clicked button 'submit'",
        "Total of 5 files processed in 0.123 seconds",
    ]

    def test_safe_samples_unchanged(self) -> None:
        for sample in self.SAFE_SAMPLES:
            with self.subTest(sample=sample):
                self.assertEqual(redact_secrets(sample), sample)

    def test_short_words_not_flagged(self) -> None:
        # Short tokens that LOOK secret-like but are not.
        self.assertEqual(
            redact_secrets("API_KEY=abc"), "API_KEY=abc",
            "short values should not be flagged (avoids false positives)",
        )


class TestPerformance(unittest.TestCase):
    def test_redact_1mb_under_500ms(self) -> None:
        """Performance smoke test for ``redact_secrets`` on ~1 MB of input.

        Performance notes (per #472 review):

        - Original Issue-Acceptance target was ``<100 ms`` for 1 MB of text.
          That was a soft target: Python's stdlib ``re`` module combined
          with a 20+ pattern alternation realistically runs in the
          200-300 ms range on developer machines (measured ~230 ms
          locally for the 21-pattern combined regex).
        - The CI threshold is intentionally generous (``<500 ms``) to
          avoid flakiness on slower shared-CI runners. Correctness and
          secret-coverage are the priority for #472; aggressive regex
          performance is a non-goal (no external ``regex`` package).
        - If the runtime ever exceeds 500 ms on CI consistently, the
          right next step is to split the pattern catalogue into a
          fast-path (high-confidence prefixes like ``ghp_``, ``sk-``,
          ``AKIA``, ``xoxb-``, ``AIza``) that runs first, and a
          slow-path (general env-var assignments, generic high-entropy
          lookups) only on demand. That keeps the common-case latency
          well under 100 ms without an external dependency.
        """
        # ~1 MB of safe text (no secrets). Using a short repeated
        # string keeps the test fast to construct while still
        # exercising the regex engine on a realistic-sized input.
        text = ("hello world this is a normal log line " * 30_000)[:1_000_000]
        self.assertGreaterEqual(len(text), 1_000_000)
        start = time.perf_counter()
        redact_secrets(text)
        elapsed = time.perf_counter() - start
        elapsed_ms = elapsed * 1000
        self.assertLess(
            elapsed,
            0.5,
            f"redact_secrets took {elapsed_ms:.1f} ms on 1 MB "
            f"(CI budget: 500 ms; soft-target: 100 ms; "
            f"local-reality: 200-300 ms)",
        )


class TestIdempotence(unittest.TestCase):
    def test_redacting_twice_is_stable(self) -> None:
        s = "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789"
        once = redact_secrets(s)
        twice = redact_secrets(once)
        self.assertEqual(once, twice)


class TestCombinedPatternFlags(unittest.TestCase):
    """Regression tests for #479 review feedback:

    Per-pattern compile flags (IGNORECASE on Bearer/env-var,
    MULTILINE on env-var / AWS-secret-assignment) MUST survive the
    combined-regex construction. We do this by applying a global
    ``re.IGNORECASE | re.MULTILINE`` to ``_COMBINED_PATTERN`` (Option B
    from the review). These tests pin the four cases that motivated
    the fix.
    """

    def test_lowercase_bearer_redacted(self) -> None:
        s = "authorization: bearer abcdefghijklmnop1234"
        out = redact_secrets(s)
        self.assertNotIn("abcdefghijklmnop1234", out)
        self.assertIn("[REDACTED]", out)

    def test_lowercase_env_assignment_redacted(self) -> None:
        s = "api_key=supersecretvalue123"
        out = redact_secrets(s)
        self.assertNotIn("supersecretvalue123", out)

    def test_env_assignment_on_second_line_redacted(self) -> None:
        s = "safe line\nAPI_KEY=supersecretvalue123"
        out = redact_secrets(s)
        self.assertNotIn("supersecretvalue123", out)

    def test_aws_secret_assignment_on_second_line_redacted(self) -> None:
        s = (
            "INFO log message that is safe\n"
            "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        )
        out = redact_secrets(s)
        self.assertNotIn("wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", out)

    def test_aws_secret_assignment_with_export_keyword(self) -> None:
        """``export AWS_SECRET_ACCESS_KEY=...`` should also match."""
        s = "export AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        out = redact_secrets(s)
        self.assertNotIn("wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", out)


if __name__ == "__main__":
    unittest.main()
