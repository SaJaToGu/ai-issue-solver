"""ais_core.json_contract — canonical success/error envelope for AIS outputs.

This module defines the JSON-Contract v1.0 used by the AIS CLI and any
future agent-facing surfaces (MCP server, Codex skills). Every output
MUST be wrapped in one of the two envelope shapes so that consumers
can rely on a stable schema.

Public API:
    SCHEMA_VERSION                  — constant, currently "1.0"
    success_envelope(command, data, ...)
    error_envelope(command, code, message, hint)
    validate_envelope(envelope)     — sanity-check shape + schema_version
"""

from __future__ import annotations

from typing import Any


SCHEMA_VERSION: str = "1.0"


__all__ = [
    "SCHEMA_VERSION",
    "success_envelope",
    "error_envelope",
    "validate_envelope",
]


def success_envelope(
    command: str,
    data: Any,
    *,
    warnings: list[str] | None = None,
    elapsed_ms: int | None = None,
) -> dict[str, Any]:
    """Wrap a successful command result in the canonical envelope."""
    raise NotImplementedError("ais_core.json_contract.success_envelope (Issue #1c)")


def error_envelope(
    command: str,
    code: str,
    message: str,
    *,
    hint: str | None = None,
    elapsed_ms: int | None = None,
) -> dict[str, Any]:
    """Wrap a failed command result in the canonical error envelope."""
    raise NotImplementedError("ais_core.json_contract.error_envelope (Issue #1c)")


def validate_envelope(envelope: dict[str, Any]) -> None:
    """Raise ValueError if ``envelope`` is not a well-formed AIS envelope."""
    raise NotImplementedError("ais_core.json_contract.validate_envelope (Issue #1c)")
