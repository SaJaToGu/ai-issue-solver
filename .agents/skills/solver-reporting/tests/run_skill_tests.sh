#!/usr/bin/env bash
# Wrapper, der die unittest-Suite des solver-reporting-Skills ausführt.
#
# Verwendung:
#   bash .agents/skills/solver-reporting/tests/run_skill_tests.sh
#   bash .agents/skills/solver-reporting/tests/run_skill_tests.sh --verbose

set -euo pipefail

# tests/ → solver-reporting/ → skills/ → .agents/ → REPO_ROOT
ROOT_DIR="$(cd "$(dirname "$0")/../../../.." && pwd)"
TESTS_DIR="$ROOT_DIR/.agents/skills/solver-reporting/tests"

PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
  # Bevorzuge Python 3.10 oder neuer, falls verfügbar — die Tests
  # nutzen ``Path.unlink(missing_ok=...)`` und Type-Hints, die erst
  # ab 3.8 / 3.10 unterstützt werden.
  for candidate in python3.12 python3.11 python3.10 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      PYTHON="$candidate"
      break
    fi
  done
fi
PYTHON="${PYTHON:-python}"

echo "=== solver-reporting Skill-Tests ==="
echo "Python: $($PYTHON --version 2>&1)"
echo "Repo-Root: $ROOT_DIR"
echo

run_test() {
  local test_name="$1"
  shift
  echo "▶ $test_name"
  if ! (cd "$TESTS_DIR" && "$PYTHON" -m unittest "$@" -v); then
    echo "✗ $test_name ist fehlgeschlagen" >&2
    exit 1
  fi
  echo
}

run_test "test_skill_artifacts" test_skill_artifacts
run_test "test_helpers" test_helpers
run_test "test_skill_workflow" test_skill_workflow

echo "=== Alle Skill-Tests bestanden ==="
