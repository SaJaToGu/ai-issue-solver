"""ais_core.json_contract — canonical success/error envelope for AIS outputs.

This module defines the JSON-Contract v1.0 used by the AIS CLI and any
future agent-facing surfaces (MCP server, Codex skills). Every output
MUST be wrapped in one of the two envelope shapes so that consumers
can rely on a stable schema.

Success shape:
    {
      "schema_version": "1.0",
      "ok": true,
      "command": "<command-name>",
      "data": <command-specific payload>,
      "warnings": [<list of warning strings>],
      "elapsed_ms": <int | omitted>
    }

Error shape:
    {
      "schema_version": "1.0",
      "ok": false,
      "command": "<command-name>",
      "error": {
        "code": "<canonical-error-code>",
        "message": "<human-readable message>",
        "hint": "<actionable hint>" | omitted
      },
      "elapsed_ms": <int | omitted>
    }

Public API:
    SCHEMA_VERSION                  — constant, currently "1.0"
    success_envelope(command, data, *, warnings=None, elapsed_ms=None)
    error_envelope(command, code, message, *, hint=None, elapsed_ms=None)
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
    """Wrap a successful command result in the canonical envelope.

    Args:
        command: Name of the command that produced the result (e.g.
            ``"solve-issue"``).
        data: Command-specific payload. May be any JSON-serializable
            value.
        warnings: Optional list of warning strings. Defaults to an
            empty list.
        elapsed_ms: Optional wall-clock duration in milliseconds.

    Returns:
        The canonical success envelope as a dict.
    """
    envelope: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "command": str(command),
        "data": data,
        "warnings": list(warnings) if warnings is not None else [],
    }
    if elapsed_ms is not None:
        envelope["elapsed_ms"] = int(elapsed_ms)
    return envelope


def error_envelope(
    command: str,
    code: str,
    message: str,
    *,
    hint: str | None = None,
    elapsed_ms: int | None = None,
) -> dict[str, Any]:
    """Wrap a failed command result in the canonical error envelope.

    Args:
        command: Name of the command that failed.
        code: Canonical error code (e.g. ``"issue_not_found"``).
        message: Human-readable error message.
        hint: Optional actionable hint shown to the user.
        elapsed_ms: Optional wall-clock duration in milliseconds.

    Returns:
        The canonical error envelope as a dict.
    """
    error_body: dict[str, Any] = {
        "code": str(code),
        "message": str(message),
    }
    if hint is not None:
        error_body["hint"] = str(hint)

    envelope: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "ok": False,
        "command": str(command),
        "error": error_body,
    }
    if elapsed_ms is not None:
        envelope["elapsed_ms"] = int(elapsed_ms)
    return envelope


def validate_envelope(envelope: dict[str, Any]) -> None:
    """Raise ``ValueError`` if ``envelope`` is not a well-formed AIS envelope.

    Validates:
        - envelope is a dict
        - ``schema_version`` matches :data:`SCHEMA_VERSION`
        - ``ok`` is a bool
        - ``command`` is present
        - success envelopes contain ``data``
        - error envelopes contain ``error`` with ``code`` and ``message``
    """
    if not isinstance(envelope, dict):
        raise ValueError(
            f"envelope must be a dict, got {type(envelope).__name__}"
        )

    if envelope.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"schema_version must be {SCHEMA_VERSION!r}, "
            f"got {envelope.get('schema_version')!r}"
        )

    if "command" not in envelope:
        raise ValueError("envelope missing required 'command' field")

    if "ok" not in envelope:
        raise ValueError("envelope missing required 'ok' field")
    if not isinstance(envelope["ok"], bool):
        raise ValueError(
            f"'ok' must be a bool, got {type(envelope['ok']).__name__}"
        )

    if envelope["ok"]:
        if "data" not in envelope:
            raise ValueError("success envelope missing required 'data' field")
    else:
        if "error" not in envelope:
            raise ValueError("error envelope missing required 'error' field")
        err = envelope["error"]
        if not isinstance(err, dict):
            raise ValueError(f"'error' must be a dict, got {type(err).__name__}")
        if "code" not in err:
            raise ValueError("error envelope missing required 'error.code'")
        if "message" not in err:
            raise ValueError("error envelope missing required 'error.message'")
