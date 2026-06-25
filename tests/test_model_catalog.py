import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import model_catalog  # noqa: E402
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
        # The static OPENCODE_FREE_MODELS is the live-discovery source
        # in tests (deterministic). The catalog should mirror it
        # exactly when live_models is provided.
        catalog = build_model_catalog(
            CONFIG, live_opencode_models=OPENCODE_FREE_MODELS
        )
        opencode_models = catalog.by_provider("opencode")

        self.assertEqual(
            [entry.model for entry in opencode_models],
            list(OPENCODE_FREE_MODELS),
        )
        self.assertTrue(all(entry.cost_tier == "free" for entry in opencode_models))
        self.assertTrue(all(entry.status == MODEL_STATUS_KNOWN for entry in opencode_models))
        self.assertEqual(
            catalog.get("opencode", OPENCODE_DEFAULT_MODEL).default_for,
            ("opencode",),
        )

    def test_opencode_live_only_models_show_up_when_discovered(self):
        # A free model that is NOT in the static fallback list
        # (e.g. a brand-new release) must surface when the live
        # discovery path returns it.
        live = OPENCODE_FREE_MODELS + ("opencode/brand-new-free",)
        catalog = build_model_catalog(CONFIG, live_opencode_models=live)
        opencode_model_names = [e.model for e in catalog.by_provider("opencode")]
        self.assertIn("opencode/brand-new-free", opencode_model_names)

    def test_opencode_default_is_first_live_model_when_static_default_missing(self):
        # If the static OPENCODE_DEFAULT_MODEL is not in the live
        # list, default_for should fall back to None for all entries
        # (no implicit "first one wins" behaviour).
        live = ("opencode/only-this-one-free",)
        catalog = build_model_catalog(CONFIG, live_opencode_models=live)
        for entry in catalog.by_provider("opencode"):
            self.assertEqual(entry.default_for, ())

    def test_opencode_no_models_returns_empty_catalog(self):
        catalog = build_model_catalog(CONFIG, live_opencode_models=())
        self.assertEqual(list(catalog.by_provider("opencode")), [])

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


class FetchOpencodeFreeModelsTests(unittest.TestCase):
    """Unit tests for the live opencode-models discovery path."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        # Capture the ORIGINAL cache-path function before patching
        # so addCleanup can restore it (even if a test raises
        # mid-flight). Manual tearDown would leak the patched path
        # on failure, polluting sibling tests with the previous
        # run's cache state.
        self._orig_cache_path = model_catalog._opencode_cache_path
        cache_file = Path(self.tmpdir.name) / "opencode_models.json"
        model_catalog._opencode_cache_path = lambda: cache_file
        self.addCleanup(
            setattr, model_catalog, "_opencode_cache_path", self._orig_cache_path,
        )

    def test_filters_to_free_models_from_live_output(self):
        """Subprocess mock: opencode models returns 4 lines; 2 are
        free, 2 are paid. The result contains only the 2 free.

        We also mock `_opencode_binary()` to be defensive — if the
        subprocess patch were to fail in some test runners, the
        binary mock ensures the test cannot accidentally shell out
        to a real `opencode models` and pick up unrelated free
        models from the live registry.
        """
        class _FakeProc:
            returncode = 0
            stdout = (
                "opencode/deepseek-v4-flash-free\n"
                "opencode/minimax-m3-pro\n"            # paid
                "opencode/mimo-v2.5-free\n"
                "opencode/gpt-4\n"                       # paid
            )
            stderr = ""
        def fake_run(*args, **kwargs):
            return _FakeProc()
        with patch("model_catalog._opencode_binary", return_value="/fake/opencode"):
            with patch("model_catalog.subprocess.run", side_effect=fake_run):
                result = model_catalog.fetch_opencode_free_models(
                    use_cache=False, ttl_seconds=0,
                )
        self.assertEqual(
            result.models,
            ("opencode/deepseek-v4-flash-free", "opencode/mimo-v2.5-free"),
        )
        self.assertEqual(result.source, "live")

    def test_fallback_when_opencode_binary_missing(self):
        with patch("model_catalog._opencode_binary", return_value=None):
            result = model_catalog.fetch_opencode_free_models(
                use_cache=False,
            )
        self.assertEqual(result.source, "fallback")
        self.assertEqual(
            result.models,
            model_catalog.OPENCODE_FREE_MODELS,
        )

    def test_fallback_when_subprocess_returns_nonzero(self):
        class _FakeProc:
            returncode = 1
            stdout = ""
            stderr = "401 Unauthorized"
        with patch("model_catalog._opencode_binary", return_value="/fake/opencode"):
            with patch("model_catalog.subprocess.run",
                       return_value=_FakeProc()):
                result = model_catalog.fetch_opencode_free_models(
                    use_cache=False,
                )
        self.assertEqual(result.source, "fallback")

    def test_cache_used_when_fresh(self):
        """First call writes to cache; second call (within TTL) reads
        from cache and does not invoke the subprocess."""
        class _FakeProc:
            returncode = 0
            stdout = "opencode/deepseek-v4-flash-free\n"
            stderr = ""
        call_count = {"n": 0}
        def fake_run(*args, **kwargs):
            call_count["n"] += 1
            return _FakeProc()
        with patch("model_catalog._opencode_binary", return_value="/fake/opencode"):
            with patch("model_catalog.subprocess.run", side_effect=fake_run):
                first = model_catalog.fetch_opencode_free_models(
                    use_cache=True, ttl_seconds=3600,
                )
                second = model_catalog.fetch_opencode_free_models(
                    use_cache=True, ttl_seconds=3600,
                )
        self.assertEqual(call_count["n"], 1, "subprocess should run once")
        self.assertEqual(first.source, "live")
        self.assertEqual(second.source, "cache")
        self.assertEqual(first.models, second.models)

    def test_cache_skipped_when_stale(self):
        """A cache entry older than the TTL triggers a fresh fetch."""
        # Write a stale cache entry directly.
        cache_file = model_catalog._opencode_cache_path()
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps({
            "fetched_at": "2020-01-01T00:00:00Z",  # ancient
            "models": ["opencode/stale-free"],
        }))

        class _FakeProc:
            returncode = 0
            stdout = "opencode/fresh-free\n"
            stderr = ""
        with patch("model_catalog._opencode_binary", return_value="/fake/opencode"):
            with patch("model_catalog.subprocess.run", return_value=_FakeProc()):
                result = model_catalog.fetch_opencode_free_models(
                    use_cache=True, ttl_seconds=3600,
                )
        self.assertEqual(result.source, "live")
        self.assertEqual(result.models, ("opencode/fresh-free",))

    def test_cache_skipped_when_use_cache_false(self):
        """use_cache=False forces a fresh fetch even with a fresh cache."""
        # Write a fresh cache entry.
        cache_file = model_catalog._opencode_cache_path()
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps({
            "fetched_at": model_catalog.datetime.now(model_catalog.timezone.utc)
                          .isoformat().replace("+00:00", "Z"),
            "models": ["opencode/cached-free"],
        }))

        class _FakeProc:
            returncode = 0
            stdout = "opencode/live-only-free\n"
            stderr = ""
        with patch("model_catalog._opencode_binary", return_value="/fake/opencode"):
            with patch("model_catalog.subprocess.run", return_value=_FakeProc()):
                result = model_catalog.fetch_opencode_free_models(
                    use_cache=False,
                )
        self.assertEqual(result.source, "live")
        self.assertEqual(result.models, ("opencode/live-only-free",))

    def test_is_free_opencode_model_recognises_patterns(self):
        from model_catalog import _is_free_opencode_model
        self.assertTrue(_is_free_opencode_model("opencode/deepseek-v4-flash-free"))
        self.assertTrue(_is_free_opencode_model("opencode/mimo-v2.5-free"))
        self.assertTrue(_is_free_opencode_model("opencode/north-mini-code-free"))
        # Exact-match list:
        self.assertTrue(_is_free_opencode_model("opencode/minimax-m2.5"))
        self.assertTrue(_is_free_opencode_model("opencode/minimax-m2.7"))
        # Paid:
        self.assertFalse(_is_free_opencode_model("opencode/minimax-m3-pro"))
        self.assertFalse(_is_free_opencode_model("opencode/gpt-4"))
        # Note: `opencode/minimax-m3-free` was previously in the static
        # OPENCODE_FREE_MODELS list (now removed because the slug is
        # no longer in the live registry). The slug itself still
        # matches the `-free` pattern, so the classifier correctly
        # marks it "free" if it ever reappears. The dead-model removal
        # is enforced by `OPENCODE_FREE_MODELS` itself, not by the
        # classifier.

    def test_dead_minimax_m3_free_is_not_in_static_fallback(self):
        """The DEAD `opencode/minimax-m3-free` slug must not appear
        in the static `OPENCODE_FREE_MODELS` fallback list. If it
        ever does, the fallback would recommend a model the live
        registry does not have."""
        self.assertNotIn(
            "opencode/minimax-m3-free",
            OPENCODE_FREE_MODELS,
        )


if __name__ == "__main__":
    unittest.main()
