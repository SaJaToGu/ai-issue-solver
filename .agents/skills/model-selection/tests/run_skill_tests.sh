#!/usr/bin/env bash
# Wrapper, der die unittest-Suite des model-selection-Skills ausführt.
#
# Verwendung:
#   bash .agents/skills/model-selection/tests/run_skill_tests.sh
#   bash .agents/skills/model-selection/tests/run_skill_tests.sh --verbose

set -euo pipefail

# tests/ → model-selection/ → skills/ → .agents/ → REPO_ROOT
ROOT_DIR="$(cd "$(dirname "$0")/../../../.." && pwd)"
TESTS_DIR="$ROOT_DIR/.agents/skills/model-selection/tests"

PYTHON="${PYTHON:-python}"

echo "=== model-selection Skill-Tests ==="
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
