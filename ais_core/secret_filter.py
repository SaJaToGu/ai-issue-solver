"""ais_core.secret_filter — detect and redact secrets in text and dicts.

This module is intentionally side-effect-free: it does no I/O, does
not mutate global state, and has no logging side-effects. It is a
pure-function helper consumed by the JSON-Contract envelope so that
no secret ever appears in AIS-CLI output.

Public API:
    redact_secrets(text)            — redact secrets in a string
    redact_dict(data)                — recursively redact secrets in a dict
    redact_list(data)                — recursively redact secrets in a list
    SECRED_PATTERNS                  — list of compiled regex patterns
"""

from __future__ import annotations

import re


# Placeholder for compiled regex patterns. Real patterns are added in
# Issue #1d. Declared as a list so callers can introspect coverage.
SECRED_PATTERNS: list[re.Pattern[str]] = []


__all__ = [
    "SECRED_PATTERNS",
    "redact_secrets",
    "redact_dict",
    "redact_list",
]


def redact_secrets(text: str) -> str:
    """Return ``text`` with all detected secrets replaced by ``[REDACTED]``."""
    raise NotImplementedError("ais_core.secret_filter.redact_secrets (Issue #1d)")


def redact_dict(data: dict) -> dict:
    """Return a deep-copy of ``data`` with secret values redacted."""
    raise NotImplementedError("ais_core.secret_filter.redact_dict (Issue #1d)")


def redact_list(data: list) -> list:
    """Return a deep-copy of ``data`` with secret values redacted."""
    raise NotImplementedError("ais_core.secret_filter.redact_list (Issue #1d)")