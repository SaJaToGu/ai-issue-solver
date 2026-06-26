#!/usr/bin/env python3
"""Shared provider/model catalogue for solver-facing model discovery."""

from __future__ import annotations

from collections import Counter
import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Iterable


MODEL_STATUS_KNOWN = "known"
MODEL_STATUS_STALE = "stale"
MODEL_STATUS_VERIFIED = "verified"
MODEL_STATUS_MISSING = "missing"

# Static fallback list, used only when the live `opencode models`
# call is unavailable (binary missing, network down, etc.). The live
# discovery path is `fetch_opencode_free_models()` below. The
# previously-listed `opencode/minimax-m3-free` was removed on
# 2026-06-25 because it is no longer in the live registry.
OPENCODE_FREE_MODELS: tuple[str, ...] = (
    "opencode/deepseek-v4-flash-free",
    "opencode/mimo-v2.5-free",
    "opencode/north-mini-code-free",
    "opencode/nemotron-3-ultra-free",
)

# Cache file for live OpenCode model discovery. One hour TTL — fast
# enough to pick up new free models in a single Solver-run batch, slow
# enough to avoid hitting the opencode CLI on every Solver invocation.
OPENCODE_MODELS_CACHE_TTL_SECONDS = 3600
OPENROUTER_MODELS_CACHE_TTL_SECONDS = 3600
OPENCODE_MODELS_CACHE_DIRNAME = "ai-issue-solver"
OPENCODE_MODELS_CACHE_FILENAME = "opencode_models.json"
OPENROUTER_MODELS_CACHE_FILENAME = "openrouter_models.json"


# Static fallback list, used only when the live OpenRouter catalog
# call is unavailable. Live discovery via `fetch_openrouter_free_models()`
# is the source of truth for benchmark sweeps.
OPENROUTER_FALLBACK_FREE_MODELS: tuple[str, ...] = (
    "cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
    "cohere/north-mini-code:free",
    "google/gemma-4-26b-a4b-it:free",
    "google/gemma-4-31b-it:free",
    "liquid/lfm-2.5-1.2b-instruct:free",
    "liquid/lfm-2.5-1.2b-thinking:free",
    "meta-llama/llama-3.2-3b-instruct:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "nousresearch/hermes-3-llama-3.1-405b:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "nvidia/nemotron-3.5-content-safety:free",
    "nvidia/nemotron-nano-12b-v2-vl:free",
    "nvidia/nemotron-nano-9b-v2:free",
    "openai/gpt-oss-120b:free",
    "openai/gpt-oss-20b:free",
    "openrouter/free",
    "openrouter/owl-alpha",
    "poolside/laguna-m.1:free",
    "poolside/laguna-xs.2:free",
    "qwen/qwen3-coder:free",
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "google/lyria-3-clip-preview",
    "google/lyria-3-pro-preview",
)


@dataclass(frozen=True)
class OpencodeModelCache:
    """On-disk cache for the live `opencode models` listing.

    Stored as JSON: `{"fetched_at": <iso8601>, "models": [...]}`.
    Stale entries are detected via `age_seconds()` and trigger a
    fresh `opencode models` call.
    """
    fetched_at: str
    models: tuple[str, ...]
    source: str = "live"  # "live" | "cache" | "fallback"

    def age_seconds(self, now_epoch: float | None = None) -> float:
        try:
            fetched_epoch = datetime.fromisoformat(
                self.fetched_at.replace("Z", "+00:00")
            ).timestamp()
        except (TypeError, ValueError):
            return float("inf")
        return (now_epoch or time.time()) - fetched_epoch


@dataclass(frozen=True)
class OpenrouterModelCache:
    """On-disk cache for the live OpenRouter free-model listing."""
    fetched_at: str
    models: tuple[str, ...]
    source: str = "live"  # "live" | "cache" | "fallback"

    def age_seconds(self, now_epoch: float | None = None) -> float:
        try:
            fetched_epoch = datetime.fromisoformat(
                self.fetched_at.replace("Z", "+00:00")
            ).timestamp()
        except (TypeError, ValueError):
            return float("inf")
        return (now_epoch or time.time()) - fetched_epoch


def _opencode_cache_path() -> Path:
    """Resolve the cache path for `opencode models` output.

    Honours `XDG_CACHE_HOME` (matches the rest of the codebase) and
    falls back to `~/.cache` on systems without it.
    """
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    cache_dir = base / OPENCODE_MODELS_CACHE_DIRNAME
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / OPENCODE_MODELS_CACHE_FILENAME


def _openrouter_cache_path() -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    cache_dir = base / OPENCODE_MODELS_CACHE_DIRNAME
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / OPENROUTER_MODELS_CACHE_FILENAME


def _read_cache() -> OpencodeModelCache | None:
    p = _opencode_cache_path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return OpencodeModelCache(
            fetched_at=str(data.get("fetched_at", "")),
            models=tuple(data.get("models", [])),
            source="cache",
        )
    except (OSError, json.JSONDecodeError):
        return None


def _write_cache(models: Iterable[str]) -> None:
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "models": list(models),
    }
    try:
        _opencode_cache_path().write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
    except OSError:
        # Cache write failures are non-fatal — fall back to memory-only.
        pass


def _read_openrouter_cache() -> OpenrouterModelCache | None:
    p = _openrouter_cache_path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return OpenrouterModelCache(
            fetched_at=str(data.get("fetched_at", "")),
            models=tuple(data.get("models", [])),
            source="cache",
        )
    except (OSError, json.JSONDecodeError):
        return None


def _write_openrouter_cache(models: Iterable[str]) -> None:
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "models": list(models),
    }
    try:
        _openrouter_cache_path().write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


def _opencode_binary() -> str | None:
    """Resolve the opencode CLI path. Honours $OPENCODE_BIN."""
    override = os.environ.get("OPENCODE_BIN")
    if override and Path(override).is_file():
        return override
    default = Path.home() / ".opencode" / "bin" / "opencode"
    if default.is_file():
        return str(default)
    return None


def _run_opencode_models() -> list[str]:
    """Call `opencode models` and parse its line-delimited output."""
    bin_path = _opencode_binary()
    if not bin_path:
        raise RuntimeError(
            "opencode CLI not found (set $OPENCODE_BIN or install "
            f"at {Path.home() / '.opencode' / 'bin' / 'opencode'})"
        )
    try:
        proc = subprocess.run(
            [bin_path, "models"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"`opencode models` failed: {exc}") from exc
    if proc.returncode != 0:
        raise RuntimeError(
            f"`opencode models` exit={proc.returncode}: {proc.stderr.strip()}"
        )
    # `opencode models` prints one slug per line on stdout.
    return [
        line.strip()
        for line in proc.stdout.splitlines()
        if line.strip()
    ]


# Pattern: a model is "free" for our purposes if its slug contains
# `-free` (e.g. `deepseek-v4-flash-free`) OR matches one of the
# historically-free provider/model combos we care about
# (`opencode/minimax-m2.5` is free in the OpenCode registry even
# though its slug lacks `-free`). The explicit list covers the
# edge cases that a simple substring match would miss.
_FREE_SLUG_PATTERNS: tuple[str, ...] = (
    "-free",            # opencode/deepseek-v4-flash-free, etc.
    "opencode/gpt-5.1-codex-mini",  # opencode labels these as free-tier
    "opencode/gpt-5.4-mini",
)
_FREE_EXACT_MATCHES: frozenset[str] = frozenset({
    # Provider-known free models whose slug does not contain "-free".
    "opencode/minimax-m2.5",
    "opencode/minimax-m2.7",
    "opencode/north-mini-code-free",
})


def _is_free_opencode_model(slug: str) -> bool:
    return (
        any(p in slug for p in _FREE_SLUG_PATTERNS)
        or slug in _FREE_EXACT_MATCHES
    )


def fetch_opencode_free_models(
    *,
    use_cache: bool = True,
    ttl_seconds: int = OPENCODE_MODELS_CACHE_TTL_SECONDS,
    now_epoch: float | None = None,
) -> OpencodeModelCache:
    """Return the current free OpenCode model set.

    Strategy:
    1. If `use_cache` and a fresh cache file exists (< ttl_seconds old),
       return the cached list with `source="cache"`.
    2. Otherwise, call `opencode models`, filter to free models,
       write to cache, return with `source="live"`.
    3. On any failure (binary missing, subprocess error, etc.),
       fall back to the static `OPENCODE_FREE_MODELS` tuple with
       `source="fallback"` so the caller can decide whether to warn.

    The `now_epoch` parameter is injectable for tests.
    """
    if use_cache:
        cached = _read_cache()
        if cached is not None and cached.age_seconds(now_epoch) < ttl_seconds:
            return OpencodeModelCache(
                fetched_at=cached.fetched_at,
                models=cached.models,
                source="cache",
            )
    try:
        raw = _run_opencode_models()
    except RuntimeError:
        return OpencodeModelCache(
            fetched_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            models=tuple(OPENCODE_FREE_MODELS),
            source="fallback",
        )
    free = tuple(m for m in raw if _is_free_opencode_model(m))
    _write_cache(free)
    return OpencodeModelCache(
        fetched_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        models=free,
        source="live",
    )


def _price_is_zero(value: Any) -> bool:
    try:
        return float(str(value)) == 0.0
    except (TypeError, ValueError):
        return False


def _is_free_openrouter_model(model: dict[str, Any]) -> bool:
    """Return True when OpenRouter pricing metadata marks a model free."""
    pricing = model.get("pricing")
    if not isinstance(pricing, dict):
        return False
    return _price_is_zero(pricing.get("prompt")) and _price_is_zero(
        pricing.get("completion")
    )


def fetch_openrouter_free_models(
    *,
    use_cache: bool = True,
    ttl_seconds: int = OPENROUTER_MODELS_CACHE_TTL_SECONDS,
    now_epoch: float | None = None,
    api_key: str | None = None,
) -> OpenrouterModelCache:
    """Return the current free OpenRouter model set.

    Strategy:
    1. If `use_cache` and a fresh cache exists, return it.
    2. Otherwise, fetch the live OpenRouter catalog, keep models whose
       pricing metadata has prompt/completion both at zero, write cache.
    3. On API/network/import failure, fall back to the static fallback
       tuple with `source="fallback"`.
    """
    if use_cache:
        cached = _read_openrouter_cache()
        if cached is not None and cached.age_seconds(now_epoch) < ttl_seconds:
            return OpenrouterModelCache(
                fetched_at=cached.fetched_at,
                models=cached.models,
                source="cache",
            )

    if api_key is None:
        api_key = os.getenv("OPENROUTER_API_KEY")

    try:
        try:
            from scripts.verify_openrouter_slugs import fetch_openrouter_models
        except ModuleNotFoundError:
            from verify_openrouter_slugs import fetch_openrouter_models

        raw = fetch_openrouter_models(api_key=api_key)
    except Exception:
        return OpenrouterModelCache(
            fetched_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            models=OPENROUTER_FALLBACK_FREE_MODELS,
            source="fallback",
        )

    free = tuple(
        model["id"]
        for model in raw
        if (
            isinstance(model, dict)
            and isinstance(model.get("id"), str)
            and _is_free_openrouter_model(model)
        )
    )
    _write_openrouter_cache(free)
    return OpenrouterModelCache(
        fetched_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        models=free,
        source="live",
    )

OPENCODE_LOW_STRENGTH_MODELS: tuple[str, ...] = OPENCODE_FREE_MODELS[:3]
OPENCODE_MEDIUM_STRENGTH_MODELS: tuple[str, ...] = (OPENCODE_FREE_MODELS[3],)
OPENCODE_DEFAULT_MODEL = OPENCODE_FREE_MODELS[0]
OPENROUTER_DIRECT_DEFAULT_MODEL = "minimax/minimax-m3"
CODEX_KNOWN_MODELS: tuple[str, ...] = ("codex/default",)


@dataclass(frozen=True)
class CatalogModel:
    provider: str
    model: str
    source: str
    status: str = MODEL_STATUS_KNOWN
    cost_tier: str | None = None
    default_for: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    last_verified_at: str | None = None
    successful_runs: int = 0

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.model}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "source": self.source,
            "status": self.status,
            "cost_tier": self.cost_tier,
            "default_for": list(self.default_for),
            "notes": list(self.notes),
            "last_verified_at": self.last_verified_at,
            "successful_runs": self.successful_runs,
        }


@dataclass(frozen=True)
class ModelCatalog:
    models: tuple[CatalogModel, ...] = field(default_factory=tuple)

    def by_provider(self, provider: str) -> list[CatalogModel]:
        return [model for model in self.models if model.provider == provider]

    def by_status(self, status: str) -> list[CatalogModel]:
        return [model for model in self.models if model.status == status]

    def get(self, provider: str, model: str) -> CatalogModel | None:
        return next(
            (
                entry for entry in self.models
                if entry.provider == provider and entry.model == model
            ),
            None,
        )

    def to_dicts(self) -> list[dict[str, Any]]:
        return [model.to_dict() for model in self.models]


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _model_status(
    model: str,
    live_models: set[str] | None,
) -> str:
    if live_models is None:
        return MODEL_STATUS_STALE
    if model in live_models:
        return MODEL_STATUS_VERIFIED
    return MODEL_STATUS_MISSING


def _configured_openrouter_models(config: dict[str, Any]) -> dict[str, set[str]]:
    # Lazy import keeps this catalog usable in tests with hand-built configs
    # without loading role routing until OpenRouter role extraction is needed.
    from role_routing_loader import get_all_roles

    configured: dict[str, set[str]] = {}
    defaults = config.get("defaults", {})
    default_model = defaults.get("model")
    if defaults.get("provider") == "openrouter" and isinstance(default_model, str) and default_model:
        configured.setdefault(default_model, set()).add("defaults")

    for role_name, role in get_all_roles(config).items():
        if role.get("provider") != "openrouter":
            continue
        model = role.get("model")
        if isinstance(model, str) and model:
            configured.setdefault(model, set()).add(role_name)
    return configured


def _run_model_from_metadata(metadata: dict[str, Any]) -> str | None:
    scorecard = metadata.get("provider_scorecard")
    if isinstance(scorecard, dict):
        actual_model = scorecard.get("actual_model")
        if isinstance(actual_model, str) and actual_model:
            return actual_model

    model_selection = metadata.get("model_selection")
    if isinstance(model_selection, dict):
        selected = model_selection.get("model")
        if isinstance(selected, str) and selected:
            return selected

    model = metadata.get("model")
    if isinstance(model, str) and model:
        return model
    return None


def _run_was_successful(metadata: dict[str, Any]) -> bool:
    status = str(metadata.get("status") or "")
    if status in {"pr_created", "pr_created_with_warning"}:
        return True

    outcome = metadata.get("run_outcome")
    if isinstance(outcome, dict):
        return outcome.get("worker_status") == "succeeded" and bool(outcome.get("has_changes"))
    return False


def collect_successful_run_counts(run_reports_root: Path | str | None) -> Counter[str]:
    counts: Counter[str] = Counter()
    if run_reports_root is None:
        return counts

    root = Path(run_reports_root)
    if not root.exists():
        return counts

    for metadata_path in root.glob("*/metadata.json"):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(metadata, dict) or not _run_was_successful(metadata):
            continue
        model = _run_model_from_metadata(metadata)
        if model:
            counts[model] += 1
    return counts


def build_openrouter_catalog(
    config: dict[str, Any],
    *,
    live_models: set[str] | None = None,
    verified_at: str | None = None,
    successful_runs: Counter[str] | None = None,
) -> list[CatalogModel]:
    configured = _configured_openrouter_models(config)
    verified_timestamp = verified_at if live_models is not None else None
    run_counts = successful_runs or Counter()

    return [
        CatalogModel(
            provider="openrouter",
            model=model,
            source="config/role_routing.yaml",
            status=_model_status(model, live_models),
            cost_tier="configured",
            default_for=tuple(sorted(roles)),
            notes=("configured role model",),
            last_verified_at=verified_timestamp,
            successful_runs=run_counts.get(model, 0),
        )
        for model, roles in sorted(configured.items())
    ]


def build_opencode_catalog(
    *,
    successful_runs: Counter[str] | None = None,
    live_models: Iterable[str] | None = None,
) -> list[CatalogModel]:
    """Build the OpenCode catalog.

    `live_models` (optional) — when provided, used directly as the
    free-model list. When `None`, falls back to
    `fetch_opencode_free_models()` which uses the cached
    `opencode models` call (TTL 1h) and falls back to the static
    `OPENCODE_FREE_MODELS` list if the binary is unavailable.

    The catalog is built from a single model list — the caller
    decides whether that's a live fetch, a cache read, or a static
    fallback. Tests inject `live_models` for determinism.
    """
    if live_models is None:
        cache_result = fetch_opencode_free_models()
        live_models = cache_result.models

    run_counts = successful_runs or Counter()
    default = OPENCODE_DEFAULT_MODEL if OPENCODE_DEFAULT_MODEL in live_models else None
    source_label = "dynamic/opencode-models-cache"
    notes = (
        f"free OpenCode model (live discovery, source={source_label})",
    )
    return [
        CatalogModel(
            provider="opencode",
            model=model,
            source=source_label,
            status=MODEL_STATUS_KNOWN,
            cost_tier="free",
            default_for=("opencode",) if model == default else (),
            notes=notes,
            successful_runs=run_counts.get(model, 0),
        )
        for model in live_models
    ]


def build_codex_catalog(
    *,
    successful_runs: Counter[str] | None = None,
) -> list[CatalogModel]:
    run_counts = successful_runs or Counter()
    return [
        CatalogModel(
            provider="codex",
            model=model,
            source="codex-cli",
            status=MODEL_STATUS_KNOWN,
            cost_tier=None,
            default_for=("codex",),
            notes=("Codex model selection is controlled by the installed Codex surface.",),
            # Older run reports store provider-level `model: codex`; fold those
            # into the synthetic catalog entry for the installed Codex surface.
            successful_runs=run_counts.get(model, 0) + run_counts.get("codex", 0),
        )
        for model in CODEX_KNOWN_MODELS
    ]


def build_model_catalog(
    config: dict[str, Any],
    *,
    live_openrouter_models: Iterable[str] | None = None,
    live_opencode_models: Iterable[str] | None = None,
    verified_at: str | None = None,
    run_reports_root: Path | str | None = None,
) -> ModelCatalog:
    live_models = set(live_openrouter_models) if live_openrouter_models is not None else None
    run_counts = collect_successful_run_counts(run_reports_root)
    effective_verified_at = verified_at or (utc_timestamp() if live_models is not None else None)

    models = [
        *build_openrouter_catalog(
            config,
            live_models=live_models,
            verified_at=effective_verified_at,
            successful_runs=run_counts,
        ),
        *build_opencode_catalog(
            successful_runs=run_counts,
            live_models=live_opencode_models,
        ),
        *build_codex_catalog(successful_runs=run_counts),
    ]
    return ModelCatalog(tuple(models))


def configured_openrouter_slug_map(config: dict[str, Any]) -> dict[str, str]:
    """Return role -> OpenRouter model slug from the shared catalog source."""
    mapping: dict[str, str] = {}
    for model, roles in _configured_openrouter_models(config).items():
        for role in roles:
            mapping[role] = model
    return dict(sorted(mapping.items()))


def load_default_catalog(
    *,
    verify_openrouter: bool = False,
    run_reports_root: Path | str | None = Path("reports") / "runs",
) -> ModelCatalog:
    from role_routing_loader import load_role_config

    config = load_role_config()
    live_models: set[str] | None = None
    if verify_openrouter:
        try:
            from scripts.verify_openrouter_slugs import extract_slugs, fetch_openrouter_models
        except ModuleNotFoundError:
            from verify_openrouter_slugs import extract_slugs, fetch_openrouter_models

        live_models = extract_slugs(
            fetch_openrouter_models(api_key=os.getenv("OPENROUTER_API_KEY"))
        )

    return build_model_catalog(
        config,
        live_openrouter_models=live_models,
        run_reports_root=run_reports_root,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="List the shared provider/model catalog used by solver workflows.",
    )
    parser.add_argument(
        "--verify-openrouter",
        action="store_true",
        help="Fetch the live OpenRouter catalog and mark configured slugs verified/missing.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of a compact table.",
    )
    parser.add_argument(
        "--run-reports-root",
        default=str(Path("reports") / "runs"),
        help="Run-report root used to count successful local model usage.",
    )
    args = parser.parse_args(argv)

    catalog = load_default_catalog(
        verify_openrouter=args.verify_openrouter,
        run_reports_root=args.run_reports_root,
    )
    if args.json:
        print(json.dumps(catalog.to_dicts(), indent=2, sort_keys=True))
        return 0

    for entry in catalog.models:
        defaults = ",".join(entry.default_for) or "-"
        success = entry.successful_runs
        print(
            f"{entry.provider:18} {entry.status:9} {entry.model:38} "
            f"default_for={defaults:24} successful_runs={success}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
