"""validation — 0.9.0 Validation Metrics & Run package.

Split from monolithic scripts/validation_run.py (1570 LOC) into modules:

  models  — data classes (ValidationIssue, RunReportData,
            ValidationConfig, ValidationMetrics)
  parsers — summary.txt + run-report reading
  metrics — compute_metrics, format_duration, format_cost,
            generate_report, validation-run persistence

This package is being merged in 3 stacked PRs:
  PR-A: models + parsers + metrics (library core, no IO)
  PR-B: + github_client + runner + pr_checks + selection (IO)
  PR-C: + cli + shim (CLI surface, wires everything)
"""
