# Next Backlog

> **📌 Sprachhinweis / Language Note:**
> Diese Datei bleibt bewusst auf Englisch, da sie als Vorlage für GitHub Issues dient
> und von KI-Workern verarbeitet wird. Siehe [Sprachrichtlinie](LANGUAGE_POLICY.md)
> This file remains in English as it serves as a template for GitHub Issues and is
> processed by AI workers. See [Language Policy](LANGUAGE_POLICY.md)

This backlog captures the next small refactoring phase after the v0.2.0 release:
reduce complexity in the largest workflow modules without changing behavior.

Create them as GitHub issues with:

```bash
python scripts/create_backlog_issues.py --backlog docs/NEXT_BACKLOG.md
python scripts/create_backlog_issues.py --backlog docs/NEXT_BACKLOG.md --apply --confirm-create
```

## 1. Refactor solve_issues worker command construction

Labels: `quality`, `workflow`

Make the worker command construction in `scripts/solve_issues.py` easier to read
and test without changing behavior.

Touches: `scripts/solve_issues.py`, `tests/test_solve_issues.py`

Keep CLI behavior and existing model support unchanged. Prefer extracting or
tightening small helper functions around worker command selection/building. Do
not change GitHub branch, commit, push, or PR behavior. Do not add new features.

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 2. Refactor status dashboard run classification helpers

Labels: `quality`, `workflow`

Make `scripts/status_dashboard.py` run classification and lifecycle helper logic
easier to maintain without changing dashboard behavior.

Touches: `scripts/status_dashboard.py`, `tests/test_status_dashboard.py`

Keep rendered dashboard behavior equivalent except for test-backed cleanup if
needed. Prefer small helper extraction or clearer predicate naming around
failed/recovered/superseded classification. Do not add new dashboard features. Do
not alter unrelated HTML/CSS layout.

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 3. Refactor batch runner retry and result bookkeeping

Labels: `quality`, `workflow`, `automation`

Make `scripts/solve_issues_batch.py` retry, delayed-job, and result bookkeeping
easier to follow without changing behavior.

Touches: `scripts/solve_issues_batch.py`, `tests/test_solve_issues_batch.py`

Preserve rate-limit requeue behavior, fallback behavior, and worker health
behavior. Prefer small helper extraction around result recording or retry
counters. Do not change `solve_issues.py` command semantics. Do not add new
features.

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`
