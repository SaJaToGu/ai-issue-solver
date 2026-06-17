#!/usr/bin/env python3
"""
role_routing_loader.py — Role-Routing-Konfiguration laden, validieren und Budget verwalten.

Lädt config/role_routing.yaml, wendet Defaults an, validiert die Struktur
und verfolgt die monatlichen Ausgaben pro Rolle zur Budget-Überwachung.

Usage:
    from role_routing_loader import load_role_config, get_role_config, check_budget
    config = load_role_config()
    role = get_role_config("solver", config)
    allowed, msg = check_budget("solver", role)
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import yaml as _yaml
except ImportError:
    _yaml = None


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

ROLE_ROUTING_PATH = PROJECT_ROOT / "config" / "role_routing.yaml"
BUDGET_TRACKER_PATH = PROJECT_ROOT / "reports" / "budget_tracker.json"

VALID_PROVIDERS = {"openrouter", "none"}
LLM_REQUIRED_FIELDS = {"provider", "model", "monthly_budget_usd"}
WORKFLOW_REQUIRED_FIELDS = {"provider", "workflow"}


def _load_yaml(filepath: Path) -> dict:
    if not filepath.exists():
        raise FileNotFoundError(
            f"Role routing file not found: {filepath}\n"
            f"Create it from config/role_routing.yaml or run:\n"
            f"  cp config/role_routing.yaml {filepath}"
        )
    with open(filepath, encoding="utf-8") as f:
        text = f.read()

    if _yaml is not None:
        data = _yaml.safe_load(text)
        if not isinstance(data, dict):
            raise ValueError("role_routing.yaml must contain a top-level mapping")
        return data

    raise ImportError(
        "PyYAML is required to parse role_routing.yaml.\n"
        "Install it: pip install pyyaml"
    )


def load_role_config(filepath: str | Path | None = None) -> dict[str, Any]:
    """
    Load and validate the role routing configuration.

    Args:
        filepath: Path to role_routing.yaml (default: PROJECT_ROOT/config/role_routing.yaml).

    Returns:
        Dict with keys 'defaults' and 'roles'. Each role has resolved
        values with defaults applied.

    Raises:
        FileNotFoundError: If the YAML file does not exist.
        ValueError: If the YAML structure is invalid.
    """
    if filepath is None:
        filepath = ROLE_ROUTING_PATH
    filepath = Path(filepath)

    data = _load_yaml(filepath)

    if "defaults" not in data:
        raise ValueError(
            "role_routing.yaml: 'defaults' section is required"
        )
    defaults = data["defaults"]
    if not isinstance(defaults, dict):
        raise ValueError("role_routing.yaml: 'defaults' must be a mapping")

    for field in ("provider", "model"):
        if field not in defaults:
            raise ValueError(
                f"role_routing.yaml: 'defaults.{field}' is required"
            )

    roles: dict[str, dict[str, Any]] = {}
    for key, value in data.items():
        if key == "defaults":
            continue
        if not isinstance(value, dict):
            raise ValueError(
                f"role_routing.yaml: entry '{key}' must be a mapping"
            )

        role = dict(defaults)
        role.update(value)
        role["_name"] = key

        provider = role.get("provider", defaults.get("provider"))
        if provider not in VALID_PROVIDERS:
            raise ValueError(
                f"role_routing.yaml: '{key}.provider' must be one of "
                f"{', '.join(sorted(VALID_PROVIDERS))}, got '{provider}'"
            )

        if provider == "openrouter":
            missing = [f for f in LLM_REQUIRED_FIELDS if f not in role]
            if missing:
                raise ValueError(
                    f"role_routing.yaml: '{key}' is missing required fields: "
                    f"{', '.join(missing)}"
                )
            if "model" not in role or not role.get("model"):
                raise ValueError(
                    f"role_routing.yaml: '{key}' (provider: openrouter) "
                    f"requires a non-empty 'model' field"
                )
        elif provider == "none":
            if "workflow" not in role or not role.get("workflow"):
                raise ValueError(
                    f"role_routing.yaml: '{key}' (provider: none) "
                    f"requires a 'workflow' field"
                )

        budget = role.get("monthly_budget_usd")
        if budget is not None:
            try:
                budget = float(budget)
            except (TypeError, ValueError):
                raise ValueError(
                    f"role_routing.yaml: '{key}.monthly_budget_usd' must be "
                    f"a number, got {budget!r}"
                )
            if budget < 0:
                raise ValueError(
                    f"role_routing.yaml: '{key}.monthly_budget_usd' must be "
                    f">= 0, got {budget}"
                )
            role["monthly_budget_usd"] = budget

        alert = role.get("cost_alert_threshold")
        if alert is not None:
            try:
                alert = float(alert)
            except (TypeError, ValueError):
                raise ValueError(
                    f"role_routing.yaml: '{key}.cost_alert_threshold' must be "
                    f"a number or null, got {alert!r}"
                )
            if not (0.0 <= alert <= 1.0):
                raise ValueError(
                    f"role_routing.yaml: '{key}.cost_alert_threshold' must be "
                    f"between 0.0 and 1.0, got {alert}"
                )
            role["cost_alert_threshold"] = alert

        roles[key] = role

    return {"defaults": defaults, "roles": roles}


def get_role_config(
    role_name: str,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Get the resolved configuration for a specific role.

    Args:
        role_name: Role name (e.g. 'planner', 'solver').
        config: Pre-loaded config (from load_role_config). Loads fresh if None.

    Returns:
        Resolved role config dict with defaults applied.

    Raises:
        KeyError: If the role is not found.
    """
    if config is None:
        config = load_role_config()
    roles = config.get("roles", {})
    if role_name not in roles:
        raise KeyError(
            f"Role '{role_name}' not found in role_routing.yaml"
        )
    return roles[role_name]


def get_all_roles(config: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Get all resolved role configurations."""
    if config is None:
        config = load_role_config()
    return dict(config.get("roles", {}))


def get_llm_roles(config: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Get only LLM roles (provider: openrouter)."""
    roles = get_all_roles(config)
    return {
        name: r for name, r in roles.items()
        if r.get("provider") == "openrouter"
    }


def get_workflow_roles(config: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Get only workflow roles (provider: none)."""
    roles = get_all_roles(config)
    return {
        name: r for name, r in roles.items()
        if r.get("provider") == "none"
    }


def get_configured_model_slugs(config: dict[str, Any] | None = None) -> set[str]:
    """Extract all model slugs from openrouter roles."""
    if config is None:
        config = load_role_config()
    slugs: set[str] = set()
    for name, role in config.get("roles", {}).items():
        if role.get("provider") == "openrouter" and role.get("model"):
            slugs.add(role["model"])
    # Also collect from defaults
    defaults = config.get("defaults", {})
    if defaults.get("provider") == "openrouter" and defaults.get("model"):
        slugs.add(defaults["model"])
    return slugs


# ── Budget Tracking ──────────────────────────────────────────


def _current_month_key() -> str:
    return datetime.now().strftime("%Y-%m")


def _load_budget_tracker() -> dict[str, dict[str, float]]:
    if BUDGET_TRACKER_PATH.exists():
        try:
            with open(BUDGET_TRACKER_PATH, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_budget_tracker(tracker: dict[str, dict[str, float]]) -> None:
    BUDGET_TRACKER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(BUDGET_TRACKER_PATH, "w", encoding="utf-8") as f:
        json.dump(tracker, f, indent=2, sort_keys=True)


def get_monthly_spending(role_name: str, month: str | None = None) -> float:
    """
    Get the total spending for a role in a given month.

    Args:
        role_name: Role name.
        month: Month key 'YYYY-MM' (default: current month).

    Returns:
        Total spending in USD.
    """
    if month is None:
        month = _current_month_key()
    tracker = _load_budget_tracker()
    return tracker.get(month, {}).get(role_name, 0.0)


def record_spending(
    role_name: str,
    cost_usd: float,
    month: str | None = None,
) -> None:
    """
    Record spending for a role in a given month.

    Args:
        role_name: Role name.
        cost_usd: Cost in USD to add (use 0.0 to record a run with no cost).
        month: Month key 'YYYY-MM' (default: current month).
    """
    if month is None:
        month = _current_month_key()
    if cost_usd < 0:
        raise ValueError(f"cost_usd must be >= 0, got {cost_usd}")
    tracker = _load_budget_tracker()
    if month not in tracker:
        tracker[month] = {}
    tracker[month][role_name] = tracker[month].get(role_name, 0.0) + cost_usd
    _save_budget_tracker(tracker)


def check_budget(
    role_name: str,
    role_config: dict[str, Any],
    month: str | None = None,
) -> tuple[bool, str | None]:
    """
    Check if a role's monthly budget allows another run.

    Args:
        role_name: Role name (for messages).
        role_config: Resolved role config dict (from get_role_config).
        month: Month key (default: current month).

    Returns:
        Tuple (is_allowed, message).
        is_allowed is True if the run can proceed.
        message is a warning/error string, or None if everything is fine.
    """
    budget = role_config.get("monthly_budget_usd", 0.0)
    if budget is None or budget <= 0:
        return True, None

    current = get_monthly_spending(role_name, month=month)
    remaining = budget - current

    # Check hard limit
    if remaining <= 0:
        return False, (
            f"[BUDGET EXCEEDED] Role '{role_name}' has exhausted its "
            f"monthly budget: {current:.4f} USD / {budget:.4f} USD. "
            f"Stop until next month or increase monthly_budget_usd."
        )

    # Check alert threshold
    threshold = role_config.get("cost_alert_threshold")
    if threshold is not None:
        ratio = current / budget
        if ratio >= threshold:
            return True, (
                f"[BUDGET WARN] Role '{role_name}' has used "
                f"{current:.4f} USD of {budget:.4f} USD "
                f"({ratio:.1%}). Alert threshold: {threshold:.0%}."
            )

    return True, None


# ── CLI ─────────────────────────────────────────────────────


def main_cli() -> None:
    """CLI entry point for budget inspection."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Role routing configuration loader and budget tracker",
    )
    parser.add_argument(
        "--show-config",
        action="store_true",
        help="Show the loaded role routing configuration",
    )
    parser.add_argument(
        "--show-spending",
        nargs="?",
        const=None,
        default=False,
        help="Show spending for a specific role (default: all roles)",
    )
    parser.add_argument(
        "--month",
        default=_current_month_key(),
        help=f"Month key YYYY-MM (default: {_current_month_key()})",
    )
    parser.add_argument(
        "--reset-spending",
        metavar="ROLE",
        nargs="?",
        const=True,
        default=False,
        help="Reset spending for a specific role (or all with --reset-spending --all)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="reset_all",
        help="With --reset-spending, reset all roles",
    )

    args = parser.parse_args()

    if args.show_config:
        config = load_role_config()
        print("Role Routing Configuration:")
        print(f"  Defaults: provider={config['defaults'].get('provider')}, "
              f"model={config['defaults'].get('model')}, "
              f"budget={config['defaults'].get('monthly_budget_usd')}")
        print(f"  Roles ({len(config['roles'])}):")
        for name, role in config["roles"].items():
            prov = role.get("provider", "?")
            model = role.get("model", role.get("workflow", "?"))
            budget = role.get("monthly_budget_usd", "N/A")
            print(f"    - {name}: provider={prov}, model={model}, budget={budget} USD")

    if args.reset_spending:
        month = args.month
        tracker = _load_budget_tracker()
        if month not in tracker:
            print(f"No spending data for {month}.")
        elif args.reset_spending is True and args.reset_all:
            tracker.pop(month, None)
            _save_budget_tracker(tracker)
            print(f"Reset all spending for {month}.")
        elif args.reset_spending is True:
            print("Specify a role name or use --all to reset all.")
        else:
            role = args.reset_spending
            if month in tracker and role in tracker[month]:
                del tracker[month][role]
                if not tracker[month]:
                    del tracker[month]
                _save_budget_tracker(tracker)
                print(f"Reset spending for '{role}' in {month}.")
            else:
                print(f"No spending data for '{role}' in {month}.")

    if args.show_spending is not False:
        month = args.month
        tracker = _load_budget_tracker()
        month_data = tracker.get(month, {})

        if args.show_spending is None:
            try:
                config = load_role_config()
                all_roles = set(config.get("roles", {}).keys())
                all_roles.update(month_data.keys())
                roles_to_show = sorted(all_roles)
            except (FileNotFoundError, ValueError):
                roles_to_show = sorted(month_data.keys())
        else:
            roles_to_show = [args.show_spending]

        print(f"\nBudget Spending for {month}:")
        total = 0.0
        for role_name in roles_to_show:
            spent = month_data.get(role_name, 0.0)
            total += spent
            try:
                cfg = load_role_config()
                budget = cfg["roles"].get(role_name, {}).get("monthly_budget_usd", "—")
            except (FileNotFoundError, ValueError):
                budget = "—"
            label = f"  {role_name}: {spent:.6f} USD"
            if budget != "—":
                label += f" / {budget} USD budget"
            print(label)
        print(f"  ─────────────────────────")
        print(f"  Total: {total:.6f} USD")

    if not any([args.show_config, args.show_spending is not False, args.reset_spending]):
        parser.print_help()


if __name__ == "__main__":
    main_cli()
