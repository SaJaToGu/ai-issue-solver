import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from model_catalog import (  # noqa: E402
    MODEL_STATUS_KNOWN,
    MODEL_STATUS_MISSING,
    MODEL_STATUS_STALE,
    MODEL_STATUS_VERIFIED,
    OPENCODE_DEFAULT_MODEL,
    OPENCODE_FREE_MODELS,
    build_model_catalog,
    collect_successful_run_counts,
    configured_openrouter_slug_map,
)


CONFIG = {
    "defaults": {
        "provider": "openrouter",
        "model": "minimax/minimax-m3",
        "monthly_budget_usd": 10.0,
    },
    "roles": {
        "solver": {
            "provider": "openrouter",
            "model": "minimax/minimax-m3",
            "monthly_budget_usd": 30.0,
        },
        "reviewer_code": {
            "provider": "openrouter",
            "model": "anthropic/claude-sonnet-4",
            "monthly_budget_usd": 5.0,
        },
        "watchdog": {
            "provider": "none",
            "workflow": "scripts/watchdog.py",
            "monthly_budget_usd": 0.0,
        },
    },
}


class ModelCatalogTests(unittest.TestCase):
    def test_configured_openrouter_slug_map_uses_roles_and_defaults(self):
        slugs = configured_openrouter_slug_map(CONFIG)

        self.assertEqual(slugs["defaults"], "minimax/minimax-m3")
        self.assertEqual(slugs["solver"], "minimax/minimax-m3")
        self.assertEqual(slugs["reviewer_code"], "anthropic/claude-sonnet-4")
        self.assertNotIn("watchdog", slugs)

    def test_openrouter_models_are_verified_or_missing_from_live_catalog(self):
        catalog = build_model_catalog(
            CONFIG,
            live_openrouter_models={"minimax/minimax-m3"},
            verified_at="2026-06-20T00:00:00+00:00",
        )

        minimax = catalog.get("openrouter", "minimax/minimax-m3")
        sonnet = catalog.get("openrouter", "anthropic/claude-sonnet-4")

        self.assertIsNotNone(minimax)
        self.assertEqual(minimax.status, MODEL_STATUS_VERIFIED)
        self.assertEqual(minimax.last_verified_at, "2026-06-20T00:00:00+00:00")
        self.assertIn("defaults", minimax.default_for)
        self.assertIn("solver", minimax.default_for)

        self.assertIsNotNone(sonnet)
        self.assertEqual(sonnet.status, MODEL_STATUS_MISSING)

    def test_openrouter_models_are_stale_without_live_catalog(self):
        catalog = build_model_catalog(CONFIG)
        model = catalog.get("openrouter", "minimax/minimax-m3")

        self.assertIsNotNone(model)
        self.assertEqual(model.status, MODEL_STATUS_STALE)
        self.assertIsNone(model.last_verified_at)

    def test_opencode_free_models_are_catalogued(self):
        catalog = build_model_catalog(CONFIG)
        opencode_models = catalog.by_provider("opencode")

        self.assertEqual([entry.model for entry in opencode_models], list(OPENCODE_FREE_MODELS))
        self.assertTrue(all(entry.cost_tier == "free" for entry in opencode_models))
        self.assertTrue(all(entry.status == MODEL_STATUS_KNOWN for entry in opencode_models))
        self.assertEqual(
            catalog.get("opencode", OPENCODE_DEFAULT_MODEL).default_for,
            ("opencode",),
        )

    def test_codex_default_is_catalogued(self):
        catalog = build_model_catalog(CONFIG)
        codex = catalog.get("codex", "codex/default")

        self.assertIsNotNone(codex)
        self.assertEqual(codex.status, MODEL_STATUS_KNOWN)
        self.assertEqual(codex.default_for, ("codex",))

    def test_successful_run_counts_from_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_metadata(
                root / "success" / "metadata.json",
                {
                    "status": "pr_created",
                    "provider_scorecard": {
                        "actual_model": "opencode/deepseek-v4-flash-free",
                    },
                },
            )
            self._write_metadata(
                root / "failed" / "metadata.json",
                {
                    "status": "started",
                    "provider_scorecard": {
                        "actual_model": "opencode/deepseek-v4-flash-free",
                    },
                    "run_outcome": {
                        "worker_status": "failed",
                        "has_changes": False,
                    },
                },
            )

            counts = collect_successful_run_counts(root)
            catalog = build_model_catalog(CONFIG, run_reports_root=root)

        self.assertEqual(counts["opencode/deepseek-v4-flash-free"], 1)
        self.assertEqual(
            catalog.get("opencode", "opencode/deepseek-v4-flash-free").successful_runs,
            1,
        )

    @staticmethod
    def _write_metadata(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
