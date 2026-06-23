#!/usr/bin/env python3
"""Thin shim for Validation Metrics & Run.

Re-exports main from the validation package. Run with --help to see
all four subcommands.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT))
sys.path.insert(0, str(_SCRIPT_DIR))

from validation.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
