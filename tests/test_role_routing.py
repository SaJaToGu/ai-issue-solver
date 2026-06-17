#!/usr/bin/env python3
"""
Tests for role_routing_loader.py and verify_openrouter_slugs.py.

Covers:
    - YAML loading, validation, and default application
    - Error handling (missing fields, invalid providers)
    - Budget tracking (spending, alerts, limits)
    - Slug verification against OpenRouter API
    - Integration with solve_issues.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))


# ── Sample YAML test data ──────────────────────────────────

VALID_YAML = """
defaults:
  provider: openrouter
  model: minimax/minimax-m3
  context_files: []
  monthly_budget_usd: 10.0
  cost_alert_threshold: 0.8

planner:
  provider: openrouter
  model: openai/gpt-5
  monthly_budget_usd: 10.0
  cost_alert_threshold: 0.8

solver:
  provider: openrouter
  model: minimax/minimax-m3
  monthly_budget_usd: 30.0
  cost_alert_threshold: 0.9

reviewer_code:
  provider: openrouter
  model: anthropic/claude-sonnet-4
  monthly_budget_usd: 5.0

watchdog:
  provider: none
  workflow: scripts/watchdog.py
  monthly_budget_usd: 0.0
"""

INVALID_DEFAULTS = """
planner:
  provider: openrouter
  model: openai/gpt-5
"""

INVALID_PROVIDER = """
defaults:
  provider: openrouter
  model: minimax/minimax-m3

planner:
  provider: unknown_provider
  model: openai/gpt-5
"""

MISSING_MODEL = """
defaults:
  provider: openrouter
  monthly_budget_usd: 10.0

planner:
  provider: openrouter
  monthly_budget_usd: 10.0
"""

MISSING_WORKFLOW = """
defaults:
  provider: openrouter
  model: minimax/minimax-m3

watchdog:
  provider: none
  monthly_budget_usd: 0.0
"""

MISSING_DEFAULTS = """
planner:
  provider: openrouter
  model: openai/gpt-5
"""


# ── Tests: role_routing_loader ─────────────────────────────


class TestLoadRoleConfig(unittest.TestCase):
    """Tests for load_role_config()."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.yaml_path = self.tmpdir / "role_routing.yaml"

    def _write_yaml(self, content: str):
        self.yaml_path.write_text(content, encoding="utf-8")

    def test_loads_valid_yaml(self):
        self._write_yaml(VALID_YAML)
        config = load_role_config(self.yaml_path)
        self.assertIn("defaults", config)
        self.assertIn("roles", config)
        self.assertIn("planner", config["roles"])
        self.assertIn("solver", config["roles"])
        self.assertEqual(len(config["roles"]), 4)

    def test_applies_defaults_to_roles(self):
        self._write_yaml(VALID_YAML)
        config = load_role_config(self.yaml_path)
        # reviewer_code doesn't set cost_alert_threshold → gets from defaults
        reviewer = config["roles"]["reviewer_code"]
        self.assertEqual(reviewer["cost_alert_threshold"], 0.8)
        # planner overrides it
        planner = config["roles"]["planner"]
        self.assertEqual(planner["cost_alert_threshold"], 0.8)

    def test_missing_defaults_raises_error(self):
        self._write_yaml(MISSING_DEFAULTS)
        with self.assertRaises(ValueError) as ctx:
            load_role_config(self.yaml_path)
        self.assertIn("defaults", str(ctx.exception))

    def test_invalid_provider_raises_error(self):
        self._write_yaml(INVALID_PROVIDER)
        with self.assertRaises(ValueError) as ctx:
            load_role_config(self.yaml_path)
        self.assertIn("unknown_provider", str(ctx.exception))

    def test_missing_model_for_openrouter_role_raises_error(self):
        self._write_yaml(MISSING_MODEL)
        with self.assertRaises(ValueError) as ctx:
            load_role_config(self.yaml_path)
        self.assertIn("model", str(ctx.exception))

    def test_missing_workflow_for_none_provider_raises_error(self):
        self._write_yaml(MISSING_WORKFLOW)
        with self.assertRaises(ValueError) as ctx:
            load_role_config(self.yaml_path)
        self.assertIn("workflow", str(ctx.exception))

    def test_file_not_found_raises_error(self):
        with self.assertRaises(FileNotFoundError):
            load_role_config(self.tmpdir / "nonexistent.yaml")

    def test_negative_budget_raises_error(self):
        bad_yaml = VALID_YAML.replace("monthly_budget_usd: 30.0",
                                      "monthly_budget_usd: -5.0")
        self._write_yaml(bad_yaml)
        with self.assertRaises(ValueError) as ctx:
            load_role_config(self.yaml_path)
        self.assertIn(">= 0", str(ctx.exception))

    def test_invalid_alert_threshold_raises_error(self):
        bad_yaml = VALID_YAML.replace("cost_alert_threshold: 0.9",
                                      "cost_alert_threshold: 1.5")
        self._write_yaml(bad_yaml)
        with self.assertRaises(ValueError) as ctx:
            load_role_config(self.yaml_path)
        self.assertIn("between 0.0 and 1.0", str(ctx.exception))

    def test_entry_must_be_mapping(self):
        bad_yaml = VALID_YAML + "\nbad_entry: just a string\n"
        self._write_yaml(bad_yaml)
        # This should either be ignored or handled gracefully
        # (a plain scalar won't have a model/provider so validation catches it)
        try:
            config = load_role_config(self.yaml_path)
            self.assertNotIn("bad_entry", config["roles"])
        except (ValueError, TypeError):
            pass  # acceptable outcomes


class TestGetRoleConfig(unittest.TestCase):
    """Tests for get_role_config()."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.yaml_path = self.tmpdir / "role_routing.yaml"
        self.yaml_path.write_text(VALID_YAML, encoding="utf-8")

    def test_get_role_config_returns_resolved(self):
        config = load_role_config(self.yaml_path)
        solver = get_role_config("solver", config)
        self.assertEqual(solver["model"], "minimax/minimax-m3")
        self.assertEqual(solver["monthly_budget_usd"], 30.0)
        self.assertEqual(solver["_name"], "solver")

    def test_get_role_config_unknown_role(self):
        config = load_role_config(self.yaml_path)
        with self.assertRaises(KeyError):
            get_role_config("nonexistent_role", config)

    def test_get_configured_model_slugs(self):
        config = load_role_config(self.yaml_path)
        slugs = get_configured_model_slugs(config)
        expected = {
            "minimax/minimax-m3",
            "openai/gpt-5",
            "anthropic/claude-sonnet-4",
        }
        self.assertEqual(slugs, expected)

    def test_get_llm_roles(self):
        config = load_role_config(self.yaml_path)
        llm = get_llm_roles(config)
        self.assertIn("planner", llm)
        self.assertIn("solver", llm)
        self.assertNotIn("watchdog", llm)

    def test_get_workflow_roles(self):
        config = load_role_config(self.yaml_path)
        wf = get_workflow_roles(config)
        self.assertIn("watchdog", wf)
        self.assertNotIn("planner", wf)


class TestBudgetTracking(unittest.TestCase):
    """Tests for budget tracking functions."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        # Patch budget tracker path to temp dir
        self.budget_patch = patch(
            "role_routing_loader.BUDGET_TRACKER_PATH",
            self.tmpdir / "budget_tracker.json",
        )
        self.budget_patch.start()

    def tearDown(self):
        self.budget_patch.stop()

    def test_record_and_retrieve_spending(self):
        record_spending("solver", 5.0, month="2026-06")
        record_spending("solver", 2.5, month="2026-06")
        record_spending("planner", 1.0, month="2026-06")

        self.assertEqual(get_monthly_spending("solver", month="2026-06"), 7.5)
        self.assertEqual(get_monthly_spending("planner", month="2026-06"), 1.0)
        self.assertEqual(get_monthly_spending("watchdog", month="2026-06"), 0.0)

    def test_different_months_are_separate(self):
        record_spending("solver", 10.0, month="2026-06")
        record_spending("solver", 5.0, month="2026-07")

        self.assertEqual(get_monthly_spending("solver", month="2026-06"), 10.0)
        self.assertEqual(get_monthly_spending("solver", month="2026-07"), 5.0)

    def test_negative_cost_raises_error(self):
        with self.assertRaises(ValueError):
            record_spending("solver", -1.0)

    def test_spending_persists_to_disk(self):
        record_spending("solver", 3.0, month="2026-06")
        # Reload from disk
        self.assertEqual(get_monthly_spending("solver", month="2026-06"), 3.0)

    def test_check_budget_under_limit(self):
        allowed, msg = check_budget("solver", {
            "monthly_budget_usd": 100.0,
            "cost_alert_threshold": 0.8,
        }, month="2026-06")
        self.assertTrue(allowed)
        self.assertIsNone(msg)

    def test_check_budget_at_alert_threshold(self):
        record_spending("solver", 80.0, month="2026-06")
        allowed, msg = check_budget("solver", {
            "monthly_budget_usd": 100.0,
            "cost_alert_threshold": 0.8,
        }, month="2026-06")
        self.assertTrue(allowed)
        self.assertIsNotNone(msg)
        self.assertIn("BUDGET WARN", msg)
        self.assertIn("80.0%", msg)

    def test_check_budget_exceeded(self):
        record_spending("solver", 100.0, month="2026-06")
        allowed, msg = check_budget("solver", {
            "monthly_budget_usd": 100.0,
        }, month="2026-06")
        self.assertFalse(allowed)
        self.assertIsNotNone(msg)
        self.assertIn("BUDGET EXCEEDED", msg)

    def test_check_budget_zero_budget(self):
        allowed, msg = check_budget("watchdog", {
            "monthly_budget_usd": 0.0,
        })
        self.assertTrue(allowed)
        self.assertIsNone(msg)

    def test_check_budget_no_budget_field(self):
        allowed, msg = check_budget("role", {})
        self.assertTrue(allowed)
        self.assertIsNone(msg)


class TestBudgetTrackerFile(unittest.TestCase):
    """Tests for budget tracker file I/O edge cases."""

    def test_missing_tracker_file(self):
        spending = get_monthly_spending("solver", month="2099-01")
        self.assertEqual(spending, 0.0)

    def test_corrupted_tracker_file(self):
        tmpdir = Path(tempfile.mkdtemp())
        tracker_path = tmpdir / "budget_tracker.json"
        tracker_path.write_text("this is not json", encoding="utf-8")
        with patch("role_routing_loader.BUDGET_TRACKER_PATH", tracker_path):
            spending = get_monthly_spending("solver", month="2099-01")
            self.assertEqual(spending, 0.0)
            record_spending("solver", 1.0, month="2099-01")
            self.assertEqual(get_monthly_spending("solver", month="2099-01"), 1.0)

    def test_tracker_directory_created(self):
        tmpdir = Path(tempfile.mkdtemp()) / "nested" / "path"
        with patch("role_routing_loader.BUDGET_TRACKER_PATH", tmpdir / "tracker.json"):
            record_spending("solver", 1.0, month="2099-01")
            self.assertTrue(tmpdir.exists())


# ── Tests: verify_openrouter_slugs ─────────────────────────


class TestVerifySlugs(unittest.TestCase):
    """Tests for verify_openrouter_slugs.py."""

    def test_extract_slugs_from_dict_format(self):
        models = [
            {"id": "openai/gpt-4"},
            {"id": "anthropic/claude-sonnet-4"},
            {"id": "mistralai/mistral-large"},
        ]
        slugs = extract_slugs(models)
        self.assertEqual(slugs, {
            "openai/gpt-4",
            "anthropic/claude-sonnet-4",
            "mistralai/mistral-large",
        })

    def test_extract_slugs_from_string_list(self):
        models = ["openai/gpt-4", "anthropic/claude-sonnet-4"]
        slugs = extract_slugs(models)
        self.assertEqual(slugs, {"openai/gpt-4", "anthropic/claude-sonnet-4"})

    def test_extract_slugs_skips_invalid_entries(self):
        models = [
            {"id": "openai/gpt-4"},
            {"no_id": "skip me"},
            "mistralai/mistral-large",
            {},
            42,
        ]
        slugs = extract_slugs(models)
        self.assertEqual(slugs, {"openai/gpt-4", "mistralai/mistral-large"})

    def test_verify_slugs_all_present(self):
        configured = {"openai/gpt-4", "anthropic/claude-sonnet-4"}
        live = {"openai/gpt-4", "anthropic/claude-sonnet-4", "mistralai/mistral-large"}
        missing = verify_slugs(configured, live)
        self.assertEqual(missing, set())

    def test_verify_slugs_some_missing(self):
        configured = {"openai/gpt-4", "nonexistent/model"}
        live = {"openai/gpt-4", "anthropic/claude-sonnet-4"}
        missing = verify_slugs(configured, live)
        self.assertEqual(missing, {"nonexistent/model"})

    def test_verify_slugs_empty_configured(self):
        missing = verify_slugs(set(), {"openai/gpt-4"})
        self.assertEqual(missing, set())

    def test_fetch_openrouter_models(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"id": "openai/gpt-4"},
                {"id": "anthropic/claude-sonnet-4"},
            ]
        }
        with patch("requests.get", return_value=mock_response) as mock_get:
            models = fetch_openrouter_models(api_key="test-key")
            self.assertEqual(len(models), 2)
            mock_get.assert_called_once()
            call_kwargs = mock_get.call_args[1]
            self.assertEqual(
                call_kwargs["headers"]["Authorization"],
                "Bearer test-key",
            )

    def test_fetch_openrouter_models_without_auth(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"data": [{"id": "openai/gpt-4"}]}
        with patch("requests.get", return_value=mock_response) as mock_get:
            models = fetch_openrouter_models()
            self.assertEqual(len(models), 1)
            call_kwargs = mock_get.call_args[1]
            self.assertNotIn("Authorization", call_kwargs.get("headers", {}))

    def test_fetch_openrouter_models_list_format(self):
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"id": "openai/gpt-4"},
            {"id": "anthropic/claude-sonnet-4"},
        ]
        with patch("requests.get", return_value=mock_response):
            models = fetch_openrouter_models()
            self.assertEqual(len(models), 2)

    def test_fetch_openrouter_models_http_error(self):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = \
            __import__("requests").HTTPError("401 Unauthorized")
        with patch("requests.get", return_value=mock_response):
            with self.assertRaises(__import__("requests").HTTPError):
                fetch_openrouter_models()

    def test_verify_configured_slugs_integration(self):
        from role_routing_loader import load_role_config
        # Write a minimal YAML with known slugs
        tmpdir = Path(tempfile.mkdtemp())
        yaml_path = tmpdir / "role_routing.yaml"
        yaml_path.write_text("""
defaults:
  provider: openrouter
  model: openai/gpt-4
  monthly_budget_usd: 10.0

planner:
  provider: openrouter
  model: anthropic/claude-sonnet-4
  monthly_budget_usd: 10.0
""", encoding="utf-8")

        config = load_role_config(yaml_path)
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"id": "openai/gpt-4"},
                {"id": "anthropic/claude-sonnet-4"},
            ]
        }
        with patch("requests.get", return_value=mock_response):
            missing = verify_configured_slugs(
                config=config,
                api_url="https://fake.example.com/models",
            )
            self.assertEqual(missing, set())

    def test_verify_configured_slugs_with_missing(self):
        from role_routing_loader import load_role_config
        tmpdir = Path(tempfile.mkdtemp())
        yaml_path = tmpdir / "role_routing.yaml"
        yaml_path.write_text("""
defaults:
  provider: openrouter
  model: openai/gpt-4
  monthly_budget_usd: 10.0

planner:
  provider: openrouter
  model: does/not-exist
  monthly_budget_usd: 10.0
""", encoding="utf-8")

        config = load_role_config(yaml_path)
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [{"id": "openai/gpt-4"}]
        }
        with patch("requests.get", return_value=mock_response):
            missing = verify_configured_slugs(
                config=config,
                api_url="https://fake.example.com/models",
            )
            self.assertEqual(missing, {"does/not-exist"})


# ── Tests: solve_issues.py integration ─────────────────────


class TestSolveIssuesIntegration(unittest.TestCase):
    """Tests for the role routing integration in solve_issues.py."""

    def test_ensure_role_routing_loads_config(self):
        from solve_issues import _ensure_role_routing
        # Reset module state
        import solve_issues
        solve_issues._ROLE_ROUTING = None
        solve_issues._ROLE_ROUTING_LOADED = False

        config = _ensure_role_routing()
        # May return None if PyYAML is not installed, but should not crash
        if config is not None:
            self.assertIn("defaults", config)
            self.assertIn("roles", config)

    def test_ensure_role_routing_caches_result(self):
        from solve_issues import _ensure_role_routing
        import solve_issues
        solve_issues._ROLE_ROUTING = None
        solve_issues._ROLE_ROUTING_LOADED = False

        config1 = _ensure_role_routing()
        config2 = _ensure_role_routing()
        self.assertIs(config1, config2)

    def test_global_role_routing_exists(self):
        import solve_issues
        # Just verify the module-level variables exist
        self.assertIsNotNone(solve_issues._ROLE_ROUTING)
        self.assertIsInstance(solve_issues._ROLE_ROUTING_LOADED, bool)
        self.assertIsInstance(solve_issues._BUDGET_TRACKING_ACTIVE, bool)


# ── Test helpers & imports (must be at bottom due to sys.path) ──


def load_role_config(filepath=None):
    """Convenience wrapper for tests."""
    from role_routing_loader import load_role_config as _load
    return _load(filepath)


def get_role_config(name, config=None):
    from role_routing_loader import get_role_config as _get
    return _get(name, config)


def get_configured_model_slugs(config=None):
    from role_routing_loader import get_configured_model_slugs as _get
    return _get(config)


def get_llm_roles(config=None):
    from role_routing_loader import get_llm_roles as _get
    return _get(config)


def get_workflow_roles(config=None):
    from role_routing_loader import get_workflow_roles as _get
    return _get(config)


def record_spending(role, cost, month=None):
    from role_routing_loader import record_spending as _rec
    return _rec(role, cost, month)


def get_monthly_spending(role, month=None):
    from role_routing_loader import get_monthly_spending as _get
    return _get(role, month)


def check_budget(role, cfg, month=None):
    from role_routing_loader import check_budget as _chk
    return _chk(role, cfg, month)


def extract_slugs(models):
    from verify_openrouter_slugs import extract_slugs as _ext
    return _ext(models)


def verify_slugs(configured, live):
    from verify_openrouter_slugs import verify_slugs as _vrf
    return _vrf(configured, live)


def fetch_openrouter_models(api_key=None, url=None):
    from verify_openrouter_slugs import fetch_openrouter_models as _fch
    return _fch(api_key=api_key, url=url or "https://fake.example.com/models")


def verify_configured_slugs(config=None, api_url=None):
    from verify_openrouter_slugs import verify_configured_slugs as _vrf
    return _vrf(config=config, api_url=api_url or "https://fake.example.com/models")


if __name__ == "__main__":
    unittest.main()
