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
import sys
from typing import Any, Iterable


MODEL_STATUS_KNOWN = "known"
MODEL_STATUS_STALE = "stale"
MODEL_STATUS_VERIFIED = "verified"
MODEL_STATUS_MISSING = "missing"

OPENCODE_FREE_MODELS: tuple[str, ...] = (
    "opencode/deepseek-v4-flash-free",
    "opencode/mimo-v2.5-free",
    "opencode/minimax-m3-free",
    "opencode/nemotron-3-ultra-free",
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
) -> list[CatalogModel]:
    run_counts = successful_runs or Counter()
    return [
        CatalogModel(
            provider="opencode",
            model=model,
            source="static/free-models",
            status=MODEL_STATUS_KNOWN,
            cost_tier="free",
            default_for=("opencode",) if model == OPENCODE_DEFAULT_MODEL else (),
            notes=("known free OpenCode model; live discovery still provider-dependent",),
            successful_runs=run_counts.get(model, 0),
        )
        for model in OPENCODE_FREE_MODELS
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
        *build_opencode_catalog(successful_runs=run_counts),
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
