#!/usr/bin/env python3
"""
verify_openrouter_slugs.py — Verify model slugs against the live OpenRouter API.

Fetches the model catalogue from https://openrouter.ai/api/v1/models and
checks that all model slugs in config/role_routing.yaml are present.

Exits with code 0 if all slugs are verified, code 1 if any slug is missing,
and code 2 if the API is unreachable.

Usage:
    python scripts/verify_openrouter_slugs.py
    python scripts/verify_openrouter_slugs.py --list-models
    python scripts/verify_openrouter_slugs.py --verbose
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:
    requests = None

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/models"
REQUEST_TIMEOUT = 30  # seconds


def fetch_openrouter_models(
    api_key: str | None = None,
    url: str = OPENROUTER_API_URL,
) -> list[dict[str, Any]]:
    """
    Fetch the model catalogue from the OpenRouter API.

    Args:
        api_key: Optional OpenRouter API key. Not strictly required for
                 the models endpoint but may help with rate limits.
        url: API endpoint URL (overridable for testing).

    Returns:
        List of model dicts from the 'data' field.

    Raises:
        requests.RequestException: On network or API errors.
        ValueError: If the response format is unexpected.
    """
    if requests is None:
        raise ImportError("requests library is required. Install: pip install requests")

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()

    data = resp.json()
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        models = data.get("data", data.get("models", []))
        if isinstance(models, list):
            return models
        raise ValueError(
            f"Unexpected API response format: 'data' field is not a list. "
            f"Keys: {list(data.keys())}"
        )
    raise ValueError(f"Unexpected API response type: {type(data).__name__}")


def extract_slugs(models: list[dict[str, Any]]) -> set[str]:
    """
    Extract model slug strings from the OpenRouter API response.

    Handles two common response formats:
    1. Each model has an 'id' field with the slug (e.g. "openai/gpt-4").
    2. Flat string list.

    Args:
        models: List of model dicts from fetch_openrouter_models().

    Returns:
        Set of model slug strings.
    """
    slugs: set[str] = set()
    for model in models:
        if isinstance(model, str):
            slugs.add(model)
        elif isinstance(model, dict):
            slug = model.get("id")
            if slug and isinstance(slug, str):
                slugs.add(slug)
    return slugs


def extract_configured_slugs(
    config: dict | None = None,
    yaml_path: str | Path | None = None,
) -> set[str]:
    """
    Extract all model slugs from the role routing configuration.

    Args:
        config: Pre-loaded role_routing config (from role_routing_loader).
                If None, loads from yaml_path or default path.
        yaml_path: Path to role_routing.yaml (default: config/role_routing.yaml).

    Returns:
        Set of model slug strings from all openrouter roles.
    """
    if config is None:
        from role_routing_loader import get_configured_model_slugs, load_role_config
        config = load_role_config(yaml_path)
        return get_configured_model_slugs(config)

    from role_routing_loader import get_configured_model_slugs
    return get_configured_model_slugs(config)


def verify_slugs(
    configured_slugs: set[str],
    live_slugs: set[str],
) -> set[str]:
    """
    Verify that all configured slugs exist in the live catalogue.

    Args:
        configured_slugs: Slugs from role_routing.yaml.
        live_slugs: Slugs from the OpenRouter API.

    Returns:
        Set of missing slugs (empty if all verified).
    """
    return configured_slugs - live_slugs


def verify_configured_slugs(
    api_key: str | None = None,
    config: dict | None = None,
    api_url: str = OPENROUTER_API_URL,
) -> set[str]:
    """
    High-level function: load config, fetch API, return missing slugs.

    Args:
        api_key: Optional OpenRouter API key.
        config: Pre-loaded role_routing config (loads fresh if None).
        api_url: API endpoint URL.

    Returns:
        Set of missing slug strings (empty if all OK).

    Raises:
        FileNotFoundError: If role_routing.yaml is missing.
        ValueError: If the YAML is invalid.
        requests.RequestException: If the API is unreachable.
    """
    from role_routing_loader import get_configured_model_slugs, load_role_config

    if config is None:
        config = load_role_config()

    configured = get_configured_model_slugs(config)
    if not configured:
        return set()

    models = fetch_openrouter_models(api_key=api_key, url=api_url)
    live = extract_slugs(models)
    return verify_slugs(configured, live)


def list_configured_slugs(
    config: dict | None = None,
) -> dict[str, str]:
    """
    List all configured slugs with their role names.

    Args:
        config: Pre-loaded role_routing config.

    Returns:
        Dict mapping role name -> model slug.
    """
    from role_routing_loader import get_all_roles, load_role_config

    if config is None:
        config = load_role_config()

    result: dict[str, str] = {}
    roles = get_all_roles(config)
    for name, role in roles.items():
        if role.get("provider") == "openrouter" and role.get("model"):
            result[name] = role["model"]
    return result


# ── CLI ─────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify OpenRouter model slugs against the live API",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="OpenRouter API key (default: OPENROUTER_API_KEY env var)",
    )
    parser.add_argument(
        "--api-url",
        default=OPENROUTER_API_URL,
        help=f"API endpoint URL (default: {OPENROUTER_API_URL})",
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="Fetch and list all live OpenRouter model slugs",
    )
    parser.add_argument(
        "--list-configured",
        action="store_true",
        help="List all configured model slugs from role_routing.yaml",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output",
    )
    parser.add_argument(
        "--skip-verification",
        action="store_true",
        help="Exit 0 even if verification fails (for offline use)",
    )

    args = parser.parse_args()

    if args.api_key is None:
        args.api_key = os.getenv("OPENROUTER_API_KEY")

    try:
        if args.list_models:
            print("Fetching live OpenRouter models ...")
            models = fetch_openrouter_models(
                api_key=args.api_key, url=args.api_url,
            )
            slugs = extract_slugs(models)
            if args.verbose:
                print(f"Found {len(slugs)} models:")
                for slug in sorted(slugs):
                    print(f"  {slug}")
            else:
                print(f"Found {len(slugs)} live model slugs. "
                      f"Use --verbose to list them.")
            sys.exit(0)

        if args.list_configured:
            slugs = list_configured_slugs()
            if not slugs:
                print("No OpenRouter model slugs found in role_routing.yaml.")
                sys.exit(0)
            print("Configured model slugs:")
            for role, slug in sorted(slugs.items()):
                print(f"  {role}: {slug}")
            sys.exit(0)

        print("Verifying OpenRouter model slugs against live API ...")
        print(f"  Endpoint: {args.api_url}")

        missing = verify_configured_slugs(
            api_key=args.api_key,
            api_url=args.api_url,
        )

        if missing:
            print(f"  ❌ Missing slugs ({len(missing)}):")
            for slug in sorted(missing):
                print(f"     - {slug}")
            print()
            print("Action needed: Update config/role_routing.yaml:")
            print("  1. Check https://openrouter.ai/models for valid slugs.")
            print("  2. Replace the stale slugs with current ones.")
            print("  3. Re-run this script to verify.")
            if args.skip_verification:
                print()
                print("⚠️  --skip-verification set, exiting with code 0.")
                sys.exit(0)
            sys.exit(1)
        else:
            configured = list_configured_slugs()
            print(f"  ✅ All {len(configured)} configured slug(s) verified. "
                  f"Models are live on OpenRouter.")
            if args.verbose:
                for role, slug in sorted(configured.items()):
                    print(f"     {role}: {slug}")
            sys.exit(0)

    except FileNotFoundError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"❌ Configuration error: {e}", file=sys.stderr)
        sys.exit(1)
    except requests.RequestException as e:
        print(f"❌ OpenRouter API error: {e}", file=sys.stderr)
        print("   Network may be unavailable. Use --skip-verification to bypass.")
        sys.exit(2)
    except ImportError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
