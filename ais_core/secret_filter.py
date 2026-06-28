"""ais_core.secret_filter — detect and redact secrets in text and dicts.

This module is intentionally side-effect-free: it does no I/O, does
not mutate global state, and has no logging side-effects. It is a
pure-function helper consumed by the JSON-Contract envelope so that
no secret ever appears in AIS-CLI output.

Coverage (>=20 patterns):

- GitHub classic PAT (``ghp_``/``gho_``/``ghu_``/``ghs_``/``ghr_`` + 36+ chars)
- GitHub fine-grained PAT (``github_pat_`` + 82 chars)
- OpenAI legacy (``sk-`` + 20+ chars) and project keys (``sk-proj-``)
- Anthropic keys (``sk-ant-``)
- AWS Access Key ID (``AKIA`` + 16 uppercase alphanum)
- AWS Secret Access Key (env-var assignment form)
- Google API Key (``AIza`` + 35 chars)
- Google OAuth token (``ya29.``)
- Slack tokens (``xox[baprs]-``)
- Slack incoming-webhook URLs
- Stripe live secret (``sk_live_``) and public (``pk_live_``) keys
- Discord bot token (3-segment base64url pattern)
- JWT (3-segment dot-separated base64url starting with ``eyJ``)
- Generic high-entropy Bearer token
- PEM private key block headers
- Env-var assignment patterns for SECRET/TOKEN/KEY/PASSWORD/PASS/API_KEY

Public API:

- :data:`SECRET_PATTERNS` — list of compiled regex patterns
- :func:`redact_secrets` — redact secrets in a string
- :func:`redact_dict` — recursively redact secrets in a dict
- :func:`redact_list` — recursively redact secrets in a list
"""

from __future__ import annotations

import re
from typing import Any


# --- pattern catalogue ------------------------------------------------------

# GitHub classic personal access tokens (ghp_, gho_, ghu_, ghs_, ghr_)
_GITHUB_CLASSIC_PAT = re.compile(r"\bgh[psour]_[A-Za-z0-9]{36,}\b")

# GitHub fine-grained PATs
_GITHUB_FINEGRAINED_PAT = re.compile(r"\bgithub_pat_[A-Za-z0-9_]{82}\b")

# OpenAI legacy and project keys
_OPENAI_LEGACY = re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")
_OPENAI_PROJECT = re.compile(r"\bsk-proj-[A-Za-z0-9_-]{20,}\b")

# Anthropic
_ANTHROPIC = re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")

# AWS Access Key ID
_AWS_ACCESS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")

# AWS Secret Access Key (env-var assignment form, value only)
_AWS_SECRET_ASSIGN = re.compile(
    r"^\s*(?:export\s+)?AWS_SECRET_ACCESS_KEY\s*=\s*['\"]?([A-Za-z0-9/+=]{40})['\"]?",
    re.IGNORECASE | re.MULTILINE,
)

# Google API Key
_GOOGLE_API_KEY = re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")

# Google OAuth token
_GOOGLE_OAUTH = re.compile(r"\bya29\.[0-9A-Za-z_-]+\b")

# Slack tokens (bot, app, user, refresh, etc.)
_SLACK_TOKEN = re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")

# Slack incoming webhook URL
_SLACK_WEBHOOK = re.compile(
    r"https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+"
)

# Stripe live keys
_STRIPE_LIVE_SECRET = re.compile(r"\bsk_live_[A-Za-z0-9]{24,}\b")
_STRIPE_LIVE_PUBLIC = re.compile(r"\bpk_live_[A-Za-z0-9]{24,}\b")

# Discord bot token (three base64url segments)
_DISCORD_TOKEN = re.compile(
    r"\b[MN][A-Za-z0-9]{23,}\.[A-Za-z0-9_-]{6,7}\.[A-Za-z0-9_-]{27,}\b"
)

# JWT (header.payload.signature, header starts with eyJ)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")

# Bearer token (case-insensitive flag passed as compile-arg to keep
# pattern.string compatible with the combined alternation regex).
_BEARER_TOKEN = re.compile(r"\bBearer\s+[A-Za-z0-9_.\-]{16,}\b", re.IGNORECASE)

# PEM private key header
_PEM_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"
)

# Env-var assignment of common sensitive names.
# We deliberately only match when the value is a "secret-looking" string
# of at least 8 chars (to avoid false positives on short assignments).
# Flags are passed as compile-args (not inline) so that this pattern's
# source string stays compatible with the combined alternation regex
# built at import time in ``_COMBINED_PATTERN``.
_ENV_SECRET_ASSIGN = re.compile(
    r"^\s*(?:export\s+)?[A-Z][A-Z0-9_]*(?:SECRET|TOKEN|KEY|PASSWORD|PASS|API_KEY|APIKEY|AUTH)\s*=\s*['\"]?([^\s'\"]{8,})['\"]?",
    re.IGNORECASE | re.MULTILINE,
)

# Twilio Account SID / API Key SID
_TWILIO_SID = re.compile(r"\b(?:AC|SK)[a-f0-9]{32}\b")

# Mailgun API key (key-<32 hex>)
_MAILGUN_KEY = re.compile(r"\bkey-[a-f0-9]{32}\b")

# SendGrid API key (SG.<22>.<43>)
_SENDGRID_KEY = re.compile(r"\bSG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}\b")


SECRET_PATTERNS: list[re.Pattern[str]] = [
    _GITHUB_CLASSIC_PAT,
    _GITHUB_FINEGRAINED_PAT,
    _OPENAI_LEGACY,
    _OPENAI_PROJECT,
    _ANTHROPIC,
    _AWS_ACCESS_KEY,
    _AWS_SECRET_ASSIGN,
    _GOOGLE_API_KEY,
    _GOOGLE_OAUTH,
    _SLACK_TOKEN,
    _SLACK_WEBHOOK,
    _STRIPE_LIVE_SECRET,
    _STRIPE_LIVE_PUBLIC,
    _DISCORD_TOKEN,
    _JWT,
    _BEARER_TOKEN,
    _PEM_PRIVATE_KEY,
    _ENV_SECRET_ASSIGN,
    _TWILIO_SID,
    _MAILGUN_KEY,
    _SENDGRID_KEY,
]


# Combined alternation regex — much faster than iterating individual
# patterns because the regex engine can scan once and dispatch in O(n).
# Built at import time from SECRET_PATTERNS so the two stay in sync.
#
# Flag note: per-pattern compile flags (e.g. ``re.IGNORECASE`` for
# ``_BEARER_TOKEN``, ``re.MULTILINE`` for env-var assignment patterns)
# are NOT preserved when we extract only ``p.pattern``. We apply a
# **global** ``re.IGNORECASE | re.MULTILINE`` here to cover the union
# of all per-pattern flags. Practical effect:
#   - case-insensitive matching across all patterns (extra matches on
#     weirdly-cased tokens; defensible — we WANT to flag anything that
#     *looks* secret regardless of case).
#   - ``^`` / ``$`` honor line boundaries across all patterns (so an
#     env-var assignment on the SECOND line of multi-line input still
#     matches).
# Other flags (DOTALL, VEROSE) are not used by any current pattern;
# add them here if a new pattern needs them.
_COMBINED_PATTERN: re.Pattern[str] = re.compile(
    "|".join(f"(?:{p.pattern})" for p in SECRET_PATTERNS),
    re.IGNORECASE | re.MULTILINE,
)


_REDACTION = "[REDACTED]"


__all__ = [
    "SECRET_PATTERNS",
    "redact_secrets",
    "redact_dict",
    "redact_list",
]


def redact_secrets(text: str) -> str:
    """Return ``text`` with all detected secrets replaced by ``[REDACTED]``.

    Args:
        text: Input string to redact.

    Returns:
        A new string with all SECRET_PATTERNS matches replaced.

    Raises:
        TypeError: if ``text`` is not a string.
    """
    if not isinstance(text, str):
        raise TypeError(
            f"redact_secrets requires a str, got {type(text).__name__}"
        )
    return _COMBINED_PATTERN.sub(_REDACTION, text)


def _redact_value(value: Any) -> Any:
    """Recursively redact a single value: str -> str, dict -> dict, list -> list."""
    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, dict):
        return redact_dict(value)
    if isinstance(value, list):
        return redact_list(value)
    if isinstance(value, tuple):
        return tuple(_redact_value(v) for v in value)
    # Numbers, bools, None, and other scalars pass through unchanged.
    return value


def redact_dict(data: dict) -> dict:
    """Return a deep-copy of ``data`` with all string values redacted.

    Recurses into nested dicts, lists, and tuples. Non-container values
    (numbers, bools, None) pass through unchanged.
    """
    if not isinstance(data, dict):
        raise TypeError(
            f"redact_dict requires a dict, got {type(data).__name__}"
        )
    return {k: _redact_value(v) for k, v in data.items()}


def redact_list(data: list) -> list:
    """Return a deep-copy of ``data`` with all string values redacted."""
    if not isinstance(data, list):
        raise TypeError(
            f"redact_list requires a list, got {type(data).__name__}"
        )
    return [_redact_value(v) for v in data]
