#!/usr/bin/env python3
"""solver_reporting.py — Run-Reports, Diagnostics, Health und Worktree-Notizen.

Dieses Modul bündelt das Reporting des Solver-Runs: Run-Report-Erzeugung und
-Metadaten, leichte Health-Dateien, OpenCode-Runtime-Diagnostics, die
Git-Änderungsübersicht sowie das Sichern (Preserved Worktrees) inklusive
Recovery-Hinweisen.

Die Funktionen werden von ``solve_issues.py`` importiert und dort weiter unter
den bisherigen Namen bereitgestellt, damit sich CLI-Verhalten, Report-Dateien
und Dashboard-Parsing nicht ändern.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from scripts.utils import clean_path_candidate, print_warn
from scripts.solver_repository import (
    branch_has_changes_against_base,
    git_output,
    git_status_porcelain,
)


RUN_REPORTS_ROOT = Path("reports") / "runs"
PRESERVED_WORKTREES_ROOT = Path("reports") / "preserved-worktrees"
PRESERVED_WORKTREE_RETENTION_DAYS = 14
GIT_SUMMARY_MAX_STATUS_LINES = 20
GIT_SUMMARY_MAX_STAT_LINES = 12
GIT_SUMMARY_STAT_GRAPH_WIDTH = 30
WORKER_OUTPUT_TAIL_LINES = 25
WORKER_OUTPUT_TAIL_CHARS = 4000
PRESERVE_WORKTREE_STATUSES = {
    "nonzero_without_changes",
    "pr_failed",
    "pr_failed_from_existing_branch",
    "push_failed",
    "rate_limit_deferred",
    "validation_failed",
}

WORKER_LIVE_OUTPUT_RE = re.compile(
    r"("
    r"\b(task|aufgabe|plan|planung|planning|reasoning|reasoning summary|"
    r"summary|zusammenfassung|warn(?:ing)?|warnung|error|fehler|failed|failure|"
    r"done|fertig|completed|abgeschlossen|result|ergebnis|final|rate limit|"
    r"retry|blocked|blockiert|commit|test|tests|read|write|edit|update|"
    r"created|updated|modified|deleted|analyse|analysiere|check|checking|"
    r"diagnostic|diagnose|auth|login|pull request|pr erstellt)\b"
    r"|^\s*(?:===|##|###|\[.*\])"
    r"|^\s*(?:\|\s*)?(?:[→✓✗•])\s+"
    r")",
    re.IGNORECASE,
)
WORKER_NOISY_OUTPUT_RE = re.compile(
    r"("
    r"^\s*(?:diff --git|index [0-9a-f]+\.\.|@@ |[+-]{3}\s|[+-](?!\s*(?:warning|error|failed)\b))"
    r"|^\s*(?:apply_patch|cat >|sed -n|python - <<|npm |pip |git diff|git status)"
    r")",
    re.IGNORECASE,
)
WORKER_NOISY_FRAGMENT_RE = re.compile(
    r"("
    r"^\s*[+-]?\s*[A-Za-z_]\w*\s*:\s*[A-Za-z_][\w\[\], .|\"']*\s*=\s*"
    r"|^\s*[+]?\s*f\.write\("
    r"|^\s*[+-]?\s*(?:self\.)?assert[A-Za-z_]*\("
    r"|^\s*[A-Za-z_][\w.\[\]0-9]*\)$"
    r"|^\s*\"[^\"]+\"\s*:\s*$"
    r"|^\s*[\"'][^\"']+[\"']\)?[,]?\s*$"
    r")",
    re.IGNORECASE,
)
OPENCODE_WAL_FAILURE_RE = re.compile(
    r"(?:PRAGMA\s+wal_checkpoint\s*\(\s*PASSIVE\s*\)|wal_checkpoint|journal_mode\s*=\s*WAL)",
    re.IGNORECASE,
)
OPENCODE_EDIT_FAILURE_RE = re.compile(r"\bEdit\s+(.+?)\s+failed\b", re.IGNORECASE)
OPENCODE_EDIT_FAILURE_REPEAT_THRESHOLD = 3
NO_CHANGE_STATUSES = {"no_changes", "skip_existing_pr", "skip_merged_pr", "skip_closed_pr"}
PIPELINE_FAILURE_STATUSES = {
    "pr_failed",
    "pr_failed_from_existing_branch",
    "push_failed",
}


@dataclass(frozen=True)
class ProviderScorecard:
    """Strukturierte Bewertung eines Provider-Modells für einen Solver-Run."""
    requested_model: str
    actual_model: str
    fallback_source: str | None = None
    duration_seconds: float | None = None
    worker_exit_code: int | None = None
    run_status: str | None = None
    pr_url: str | None = None
    test_command: str | None = None
    test_result: str | None = None
    no_change: bool | None = None
    fallback_used: bool = False
    
    # Kosteninformationen
    estimated_cost: float | None = None
    cost_currency: str | None = None
    cost_confidence: str | None = None  # z.B. "low", "medium", "high", "unavailable"
    cost_source: str | None = None  # z.B. "provider_api", "estimated", "manual"

    # Post-Solve Test-Delta
    test_delta_passed_before: int | None = None
    test_delta_passed_after: int | None = None
    test_delta_failed_before: int | None = None
    test_delta_failed_after: int | None = None
    test_delta_outcome: str | None = None  # "all_green", "unchanged", "new_failures", "unknown"


@dataclass(frozen=True)
class RunReport:
    path: Path
    repo: str
    issue_number: int
    issue_title: str
    branch: str
    model: str


@dataclass(frozen=True)
class OpenCodeRuntimeDiagnostics:
    wal_failure: bool = False
    edit_loop: bool = False
    edit_failure_count: int = 0
    edit_failure_files: tuple[str, ...] = ()

    @property
    def has_findings(self) -> bool:
        return self.wal_failure or self.edit_loop


def infer_test_status(test_result: str | None) -> str:
    if not test_result:
        return "unknown"
    lowered = test_result.lower()
    if any(marker in lowered for marker in ("fail", "failed", "error")):
        return "failed"
    if any(marker in lowered for marker in ("pass", "passed", "ok", "success")):
        return "passed"
    return "unknown"


def build_run_outcome(status: str,
                      worker_result=None,
                      pr_url: str | None = None,
                      preserved_worktree_path: Path | str | None = None,
                      git_change_summary: list[str] | None = None,
                      test_result: str | None = None) -> dict[str, str | bool]:
    """Build a compact outcome schema for benchmark and dashboard comparisons."""
    if worker_result is None:
        worker_status = "not_started"
    else:
        worker_status = "succeeded" if worker_result.returncode == 0 else "failed"

    has_changes = bool(git_change_summary)
    test_status = infer_test_status(test_result)
    preserved = bool(preserved_worktree_path)

    if pr_url:
        delivery_status = "pr_created"
    elif status == "push_failed":
        delivery_status = "push_failed"
    elif status in {"pr_failed", "pr_failed_from_existing_branch"}:
        delivery_status = "pr_failed"
    elif status in NO_CHANGE_STATUSES:
        delivery_status = "not_applicable"
    elif status == "pr_skipped":
        delivery_status = "pushed_without_pr" if has_changes else "not_applicable"
    elif status == "started":
        delivery_status = "incomplete"
    else:
        delivery_status = "unknown"

    if status in NO_CHANGE_STATUSES:
        failure_class = "noop"
    elif pr_url or status.startswith("pr_created"):
        failure_class = "success"
    elif status == "pr_skipped":
        failure_class = "success" if has_changes else "noop"
    elif status in PIPELINE_FAILURE_STATUSES and (has_changes or preserved):
        failure_class = "pipeline_failure"
    elif worker_result is not None and worker_result.returncode != 0 and not has_changes:
        failure_class = "model_failure"
    elif status == "validation_failed":
        failure_class = "validation_failure"
    elif status == "started":
        failure_class = "interrupted"
    elif status.endswith("_failed"):
        failure_class = "pipeline_failure" if has_changes or preserved else "runtime_failure"
    else:
        failure_class = "unknown"

    if preserved:
        recovery_status = "preserved_worktree"
    elif failure_class in {"model_failure", "runtime_failure", "interrupted"}:
        recovery_status = "retry_clean"
    elif failure_class == "validation_failure":
        recovery_status = "manual_review"
    else:
        recovery_status = "none"

    return {
        "worker_status": worker_status,
        "has_changes": has_changes,
        "test_status": test_status,
        "delivery_status": delivery_status,
        "failure_class": failure_class,
        "recovery_status": recovery_status,
    }


def should_surface_worker_line(line: str) -> bool:
    """Filtert laute Detailausgabe und laesst relevante Statuszeilen live durch."""
    stripped = line.strip()
    if not stripped:
        return False
    if WORKER_NOISY_OUTPUT_RE.search(stripped):
        return False
    if WORKER_NOISY_FRAGMENT_RE.search(stripped):
        return False
    return bool(WORKER_LIVE_OUTPUT_RE.search(stripped))


def format_worker_output_tail(output: str) -> str:
    cleaned = output.strip()
    if not cleaned:
        return ""

    lines = cleaned.splitlines()
    surfaced_lines = [line for line in lines if should_surface_worker_line(line)]
    tail_lines = surfaced_lines[-WORKER_OUTPUT_TAIL_LINES:] if surfaced_lines else lines[-WORKER_OUTPUT_TAIL_LINES:]
    tail = "\n".join(tail_lines)
    if len(tail) > WORKER_OUTPUT_TAIL_CHARS:
        tail = tail[-WORKER_OUTPUT_TAIL_CHARS:]
        return f"...\n{tail}"
    return tail


def changed_status_paths(status_lines: list[str]) -> list[str]:
    paths = []
    for line in status_lines:
        if len(line) < 4:
            continue
        paths.append(line[3:])
    return paths


def count_file_lines(path: Path) -> int:
    try:
        data = path.read_bytes()
    except OSError:
        return 0
    if not data:
        return 0
    return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


def pluralize_de(count: int, singular: str, plural: str) -> str:
    return singular if count == 1 else plural


def format_untracked_file_stats(repo_dir: str, status_lines: list[str]) -> tuple[list[tuple[str, int]], int]:
    repo_root = Path(repo_dir)
    stats = []
    insertions = 0
    for status_line in status_lines:
        if not status_line.startswith("?? "):
            continue
        relative_path = status_line[3:]
        path = repo_root / relative_path
        if not path.is_file():
            continue
        line_count = count_file_lines(path)
        insertions += line_count
        stats.append((relative_path, line_count))
    return stats, insertions


def format_untracked_diff_stat_lines(untracked_stats: list[tuple[str, int]],
                                     path_width: int = 0) -> list[str]:
    if not untracked_stats:
        return []
    path_width = max(path_width, max(len(path) for path, _line_count in untracked_stats))
    lines = []
    for relative_path, line_count in untracked_stats:
        pluses = "+" * min(max(line_count, 1), GIT_SUMMARY_STAT_GRAPH_WIDTH)
        lines.append(f"{relative_path:<{path_width}} | {line_count:>3} {pluses}")
    return lines


def normalize_diff_stat_lines(stat_lines: list[str],
                              untracked_stats: list[tuple[str, int]]) -> list[str]:
    file_lines = []
    summary_lines = []
    path_width = 0
    for line in stat_lines:
        if "|" not in line:
            summary_lines.append(line)
            continue
        path_width = max(path_width, len(line.split("|", 1)[0].rstrip()))
        file_lines.append(line)

    untracked_lines = format_untracked_diff_stat_lines(untracked_stats, path_width)
    return file_lines + untracked_lines + summary_lines


def format_git_change_summary(repo_dir: str, git_status: str | None = None) -> list[str]:
    status = git_status if git_status is not None else git_status_porcelain(repo_dir)
    status_lines = [line for line in status.splitlines() if line.strip()]
    if not status_lines:
        return []

    summary = ["Git-Änderungsübersicht:"]
    untracked_stats, untracked_insertions = format_untracked_file_stats(
        repo_dir,
        status_lines,
    )
    stat = git_output(repo_dir, ["diff", "--stat", "HEAD", "--"])
    stat_lines = normalize_diff_stat_lines(
        [line for line in stat.splitlines() if line.strip()],
        untracked_stats,
    )
    if stat_lines:
        for line in stat_lines[:GIT_SUMMARY_MAX_STAT_LINES]:
            summary.append(f"  {line}")
        if len(stat_lines) > GIT_SUMMARY_MAX_STAT_LINES:
            summary.append(
                f"  ... {len(stat_lines) - GIT_SUMMARY_MAX_STAT_LINES} weitere Stat-Zeilen"
            )
    else:
        changed_paths = changed_status_paths(status_lines)
        for path in changed_paths[:GIT_SUMMARY_MAX_STATUS_LINES]:
            summary.append(f"  {path}")
        if len(changed_paths) > GIT_SUMMARY_MAX_STATUS_LINES:
            summary.append(
                f"  ... {len(changed_paths) - GIT_SUMMARY_MAX_STATUS_LINES} weitere Dateien"
            )

    if untracked_insertions:
        summary.append(
            f"  {len(untracked_stats)} neue "
            f"{pluralize_de(len(untracked_stats), 'Datei', 'Dateien')}, "
            f"{untracked_insertions} "
            f"{pluralize_de(untracked_insertions, 'eingefuegte Zeile', 'eingefuegte Zeilen')}"
        )
    return summary


def print_git_change_summary(repo_dir: str, git_status: str) -> None:
    for line in format_git_change_summary(repo_dir, git_status):
        print(f"      {line}")


def safe_run_repo_name(repo: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", repo).strip("-") or "repo"


def create_run_report(repo: str, issue_number: int, branch: str, model: str,
                      now_fn=datetime.now,
                      issue_title: str = "",
                      run_dir: Path | str | None = None) -> RunReport | None:
    if run_dir is None:
        timestamp = now_fn().strftime("%Y%m%d-%H%M%S-%f")
        run_dir = RUN_REPORTS_ROOT / f"{timestamp}-{safe_run_repo_name(repo)}-issue-{issue_number}"
        exist_ok = False
    else:
        run_dir = Path(run_dir)
        exist_ok = True
    try:
        run_dir.mkdir(parents=True, exist_ok=exist_ok)
    except OSError as exc:
        print_warn(f"Run-Report konnte nicht angelegt werden: {exc}")
        return None
    return RunReport(run_dir, repo, issue_number, issue_title, branch, model)


def detect_opencode_runtime_diagnostics(output: str) -> OpenCodeRuntimeDiagnostics:
    """Erkennt bekannte OpenCode-Runtime-Probleme aus Worker-Output."""
    edit_failures = [
        clean_path_candidate(match.group(1))
        for match in OPENCODE_EDIT_FAILURE_RE.finditer(output)
    ]
    edit_failure_files = tuple(dict.fromkeys(edit_failures))
    return OpenCodeRuntimeDiagnostics(
        wal_failure=bool(OPENCODE_WAL_FAILURE_RE.search(output)),
        edit_loop=len(edit_failures) >= OPENCODE_EDIT_FAILURE_REPEAT_THRESHOLD,
        edit_failure_count=len(edit_failures),
        edit_failure_files=edit_failure_files,
    )


def opencode_runtime_diagnostic_lines(diagnostics: OpenCodeRuntimeDiagnostics) -> list[str]:
    lines = []
    if diagnostics.wal_failure:
        lines.extend([
            "OpenCode SQLite/WAL-Fehler erkannt.",
            "Recovery: OpenCode-Prozesse beenden und nur opencode.db-wal/opencode.db-shm entfernen.",
            "Nicht auth.json oder opencode.db löschen.",
        ])
    if diagnostics.edit_loop:
        files = ", ".join(diagnostics.edit_failure_files[:5]) or "unbekannte Dateien"
        lines.append(
            "OpenCode Edit-Loop-Risiko erkannt: "
            f"{diagnostics.edit_failure_count} fehlgeschlagene Edit-Versuche ({files})."
        )
    return lines


def print_opencode_runtime_diagnostics(diagnostics: OpenCodeRuntimeDiagnostics) -> None:
    for line in opencode_runtime_diagnostic_lines(diagnostics):
        print_warn(line)


def write_run_health(report: RunReport, output: str = "",
                     last_activity_at: datetime | None = None,
                     status: str = "running",
                     phase: str = "",
                     worker_pid: int | None = None) -> None:
    """Speichert leichte Health-Daten, ohne den eigentlichen Summary-Report umzubauen."""
    last_activity_at = last_activity_at or datetime.now()
    tail = format_worker_output_tail(output)
    opencode_diagnostics = detect_opencode_runtime_diagnostics(output)
    payload = {
        "status": status,
        "phase": phase,
        "last_activity_at": last_activity_at.isoformat(timespec="seconds"),
        "last_report_update_at": datetime.now().isoformat(timespec="seconds"),
        "output_tail": tail,
        "process": {
            "runner_pid": os.getpid(),
            "parent_pid": os.getppid(),
            "worker_pid": worker_pid,
        },
        "opencode_runtime": {
            "wal_failure": opencode_diagnostics.wal_failure,
            "edit_loop": opencode_diagnostics.edit_loop,
            "edit_failure_count": opencode_diagnostics.edit_failure_count,
            "edit_failure_files": list(opencode_diagnostics.edit_failure_files),
            "diagnostic_lines": opencode_runtime_diagnostic_lines(opencode_diagnostics),
        },
    }
    try:
        (report.path / "health.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        if tail:
            (report.path / "output-tail.log").write_text(tail + "\n", encoding="utf-8")
    except OSError as exc:
        print_warn(f"Run-Health konnte nicht gespeichert werden: {exc}")


def preserved_worktree_cleanup_command(retention_days: int = PRESERVED_WORKTREE_RETENTION_DAYS) -> str:
    return (
        "python scripts/solve_issues.py --cleanup-preserved-worktrees "
        f"--retention-days {retention_days}"
    )


def preserved_worktree_recovery_note(path: Path, branch: str, base_branch: str | None = None) -> str:
    diff_base = f"origin/{base_branch}...HEAD" if base_branch else "origin/main...HEAD"
    return "\n".join([
        "Manuelle Recovery:",
        f"  cd {path}",
        "  git status --short",
        f"  git diff --stat {diff_base}",
        f"  git push origin HEAD:{branch}",
        "  # Danach PR manuell erstellen oder den Solver erneut starten.",
    ])


def write_preserved_worktree_readme(path: Path, repo: str, issue_number: int,
                                    branch: str, status: str,
                                    base_branch: str | None = None) -> None:
    content = "\n".join([
        "# Preserved AI Solver Worktree",
        "",
        f"- Repository: `{repo}`",
        f"- Issue: `#{issue_number}`",
        f"- Branch: `{branch}`",
        f"- Failure status: `{status}`",
        "",
        preserved_worktree_recovery_note(path, branch, base_branch),
        "",
        "Aufraeumen:",
        "",
        f"```bash\n{preserved_worktree_cleanup_command()}\n```",
        "",
    ])
    (path / "RECOVERY.md").write_text(content, encoding="utf-8")


def sanitize_preserved_remote(repo_dir: Path, owner: str, repo: str) -> None:
    public_url = f"https://github.com/{owner}/{repo}.git"
    subprocess.run(
        ["git", "remote", "set-url", "origin", public_url],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "--unset-all", "remote.origin.pushurl"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )


def unique_preserved_worktree_path(report: RunReport, repo: str) -> Path:
    base = PRESERVED_WORKTREES_ROOT / report.path.name / safe_run_repo_name(repo)
    candidate = base
    suffix = 2
    while candidate.exists():
        candidate = base.with_name(f"{base.name}-{suffix}")
        suffix += 1
    return candidate


def worktree_has_recoverable_changes(repo_dir: str, base_branch: str) -> bool:
    return bool(git_status_porcelain(repo_dir).strip()) or branch_has_changes_against_base(
        repo_dir, base_branch
    )


def should_preserve_worktree(status: str, repo_dir: str, base_branch: str,
                             changes_exist: bool = False) -> bool:
    if status not in PRESERVE_WORKTREE_STATUSES:
        return False
    return changes_exist or worktree_has_recoverable_changes(repo_dir, base_branch)


def preserve_worker_worktree(repo_dir: str, report: RunReport, owner: str, repo: str,
                             issue_number: int, branch: str, status: str,
                             base_branch: str) -> Path | None:
    source = Path(repo_dir)
    if not source.exists():
        return None

    destination = unique_preserved_worktree_path(report, repo)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        sanitize_preserved_remote(source, owner, repo)
        shutil.move(str(source), str(destination))
    except (OSError, shutil.Error) as exc:
        print_warn(f"Worktree konnte nicht gesichert werden: {exc}")
        return None

    try:
        write_preserved_worktree_readme(
            destination,
            repo=repo,
            issue_number=issue_number,
            branch=branch,
            status=status,
            base_branch=base_branch,
        )
    except OSError as exc:
        print_warn(f"Recovery-Hinweis konnte nicht geschrieben werden: {exc}")
    print_warn(f"Worktree fuer Recovery gesichert: {destination}")
    return destination


def create_provider_scorecard(
    report: RunReport,
    status: str,
    worker_result=None,
    pr_url: str | None = None,
    model_selection_metadata: dict | None = None,
    test_command: str | None = None,
    test_result: str | None = None,
    test_delta_passed_before: int | None = None,
    test_delta_passed_after: int | None = None,
    test_delta_failed_before: int | None = None,
    test_delta_failed_after: int | None = None,
    test_delta_outcome: str | None = None,
) -> ProviderScorecard:
    """Erstellt eine Provider-Scorecard für den Run."""
    fallback_source = model_selection_metadata.get('fallback_from') if model_selection_metadata else None
    fallback_used = bool(fallback_source)

    # Kompatibilität mit WorkerRunResult und anderen Worker-Typen
    duration_seconds = None
    if worker_result and hasattr(worker_result, 'duration_seconds'):
        duration_seconds = worker_result.duration_seconds
    elif worker_result and hasattr(worker_result, 'duration'):
        duration_seconds = worker_result.duration

    worker_exit_code = worker_result.returncode if worker_result else None

    # Modellinformationen aufbereiten
    requested_model = model_selection_metadata.get('model', report.model) if model_selection_metadata else report.model
    actual_model = report.model

    # Konkreten Modellnamen anhängen, falls vorhanden
    if model_selection_metadata and 'model_name' in model_selection_metadata:
        effective_model_name = model_selection_metadata['model_name']
        if effective_model_name and effective_model_name not in actual_model:
            actual_model = f"{actual_model} ({effective_model_name})"
    elif hasattr(report, 'model_name') and report.model_name:
        effective_model_name = report.model_name
        if effective_model_name and effective_model_name not in actual_model:
            actual_model = f"{actual_model} ({effective_model_name})"

    # Fallback-Informationen hinzufügen
    if fallback_source and fallback_used:
        actual_model = f"{actual_model} (Fallback von {fallback_source})"

    return ProviderScorecard(
        requested_model=requested_model,
        actual_model=actual_model,
        fallback_source=fallback_source,
        duration_seconds=duration_seconds,
        worker_exit_code=worker_exit_code,
        run_status=status,
        pr_url=pr_url,
        test_command=test_command,
        test_result=test_result,
        no_change=status in {"no_changes", "skip_existing_pr", "skip_merged_pr", "skip_closed_pr"},
        fallback_used=fallback_used,
        
        # Kosteninformationen aus model_selection_metadata extrahieren
        estimated_cost=model_selection_metadata.get('estimated_cost') if model_selection_metadata else None,
        cost_currency=model_selection_metadata.get('cost_currency') if model_selection_metadata else None,
        cost_confidence=model_selection_metadata.get('cost_confidence') if model_selection_metadata else None,
        cost_source=model_selection_metadata.get('cost_source') if model_selection_metadata else None,

        # Test-Delta-Werte weiterreichen
        test_delta_passed_before=test_delta_passed_before,
        test_delta_passed_after=test_delta_passed_after,
        test_delta_failed_before=test_delta_failed_before,
        test_delta_failed_after=test_delta_failed_after,
        test_delta_outcome=test_delta_outcome,
    )


def write_run_report(report: RunReport, status: str,
                      worker_result=None,
                      pr_url: str | None = None,
                      note: str | None = None,
                      preserved_worktree_path: Path | str | None = None,
                      base_branch: str | None = None,
                      git_change_summary: list[str] | None = None,
                      vibe_log_snippet: str | None = None,
                      resource_diagnostics=None,
                      model_selection_metadata: dict | None = None,
                      test_command: str | None = None,
                      test_result: str | None = None,
                      test_delta_passed_before: int | None = None,
                      test_delta_passed_after: int | None = None,
                      test_delta_failed_before: int | None = None,
                      test_delta_failed_after: int | None = None,
                      test_delta_outcome: str | None = None) -> Path | None:
    worker_exit_code = "" if worker_result is None else str(worker_result.returncode)
    worker_output = "" if worker_result is None else worker_result.output
    output_tail = format_worker_output_tail(worker_output)
    opencode_diagnostics = detect_opencode_runtime_diagnostics(worker_output)
    opencode_diagnostic_lines = opencode_runtime_diagnostic_lines(opencode_diagnostics)
    last_activity_at = worker_result.last_activity_at if worker_result else None
    pr_value = pr_url or ""
    preserved_value = str(preserved_worktree_path) if preserved_worktree_path else ""
    cleanup_command = preserved_worktree_cleanup_command() if preserved_value else ""
    vibe_snippet = vibe_log_snippet or ""
    run_outcome = build_run_outcome(
        status,
        worker_result=worker_result,
        pr_url=pr_url,
        preserved_worktree_path=preserved_worktree_path,
        git_change_summary=git_change_summary,
        test_result=test_result,
    )

    # Ressourcen-Diagnosen als optionaler Bestandteil
    resource_diag_dict = resource_diagnostics.to_report_dict() if resource_diagnostics else {}

    try:
        if worker_result is not None:
            (report.path / "worker-output.log").write_text(worker_output, encoding="utf-8")
        if output_tail:
            (report.path / "output-tail.log").write_text(output_tail + "\n", encoding="utf-8")

        # Provider-Scorecard erstellen
        scorecard = create_provider_scorecard(
            report, status, worker_result, pr_url, model_selection_metadata, test_command, test_result,
            test_delta_passed_before=test_delta_passed_before,
            test_delta_passed_after=test_delta_passed_after,
            test_delta_failed_before=test_delta_failed_before,
            test_delta_failed_after=test_delta_failed_after,
            test_delta_outcome=test_delta_outcome,
        )

        metadata = {
            "status": status,
            "selected_repo": report.repo,
            "repo": report.repo,
            "issue_number": report.issue_number,
            "issue": report.issue_number,
            "issue_title": report.issue_title,
            "branch": report.branch,
            "model": report.model,
            "worker_exit_code": worker_exit_code,
            "last_activity_at": last_activity_at.isoformat(timespec="seconds") if last_activity_at else "",
            "last_report_update_at": datetime.now().isoformat(timespec="seconds"),
            "pr_url": pr_value,
            "note": note or "",
            "preserved_worktree": preserved_value,
            "cleanup_command": cleanup_command,
            "git_change_summary": git_change_summary or [],
            "vibe_log_snippet": vibe_snippet,
            "opencode_runtime": {
                "wal_failure": opencode_diagnostics.wal_failure,
                "edit_loop": opencode_diagnostics.edit_loop,
                "edit_failure_count": opencode_diagnostics.edit_failure_count,
                "edit_failure_files": list(opencode_diagnostics.edit_failure_files),
                "diagnostic_lines": opencode_diagnostic_lines,
            },
            "resource_diagnostics": resource_diag_dict,
            "run_outcome": run_outcome,
            "model_selection": model_selection_metadata or {},
             "provider_scorecard": {
                "requested_model": scorecard.requested_model,
                "actual_model": scorecard.actual_model,
                "fallback_source": scorecard.fallback_source,
                "duration_seconds": scorecard.duration_seconds,
                "worker_exit_code": scorecard.worker_exit_code,
                "run_status": scorecard.run_status,
                "pr_url": scorecard.pr_url,
                "test_command": scorecard.test_command,
                "test_result": scorecard.test_result,
                "no_change": scorecard.no_change,
                "fallback_used": scorecard.fallback_used,
                "estimated_cost": scorecard.estimated_cost,
                "cost_currency": scorecard.cost_currency,
                "cost_confidence": scorecard.cost_confidence,
                "cost_source": scorecard.cost_source,
                "test_delta_passed_before": scorecard.test_delta_passed_before,
                "test_delta_passed_after": scorecard.test_delta_passed_after,
                "test_delta_failed_before": scorecard.test_delta_failed_before,
                "test_delta_failed_after": scorecard.test_delta_failed_after,
                "test_delta_outcome": scorecard.test_delta_outcome,
            },
        }
        (report.path / "metadata.json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        summary_lines = [
            f"status: {status}",
            f"selected_repo: {report.repo}",
            f"repo: {report.repo}",
            f"issue_number: {report.issue_number}",
            f"issue: {report.issue_number}",
            f"issue_title: {report.issue_title}",
            f"branch: {report.branch}",
            f"model: {report.model}",
            f"worker_exit_code: {worker_exit_code}",
            f"last_activity_at: {last_activity_at.isoformat(timespec='seconds') if last_activity_at else ''}",
            f"last_report_update_at: {datetime.now().isoformat(timespec='seconds')}",
            f"pr_url: {pr_value}",
            f"preserved_worktree: {preserved_value}",
            f"run_outcome_worker_status: {run_outcome['worker_status']}",
            f"run_outcome_has_changes: {run_outcome['has_changes']}",
            f"run_outcome_test_status: {run_outcome['test_status']}",
            f"run_outcome_delivery_status: {run_outcome['delivery_status']}",
            f"run_outcome_failure_class: {run_outcome['failure_class']}",
            f"run_outcome_recovery_status: {run_outcome['recovery_status']}",
            f"provider_scorecard_requested_model: {scorecard.requested_model}",
            f"provider_scorecard_actual_model: {scorecard.actual_model}",
            f"provider_scorecard_fallback_source: {scorecard.fallback_source or ''}",
            f"provider_scorecard_duration_seconds: {scorecard.duration_seconds or ''}",
            f"provider_scorecard_worker_exit_code: {scorecard.worker_exit_code or ''}",
            f"provider_scorecard_run_status: {scorecard.run_status or ''}",
            f"provider_scorecard_pr_url: {scorecard.pr_url or ''}",
            f"provider_scorecard_test_command: {scorecard.test_command or ''}",
            f"provider_scorecard_test_result: {scorecard.test_result or ''}",
            f"provider_scorecard_no_change: {scorecard.no_change}",
            f"provider_scorecard_fallback_used: {scorecard.fallback_used}",
            f"provider_scorecard_estimated_cost: {scorecard.estimated_cost or ''}",
            f"provider_scorecard_cost_currency: {scorecard.cost_currency or ''}",
            f"provider_scorecard_cost_confidence: {scorecard.cost_confidence or ''}",
            f"provider_scorecard_cost_source: {scorecard.cost_source or ''}",
            f"provider_scorecard_test_delta_passed_before: {scorecard.test_delta_passed_before or ''}",
            f"provider_scorecard_test_delta_passed_after: {scorecard.test_delta_passed_after or ''}",
            f"provider_scorecard_test_delta_failed_before: {scorecard.test_delta_failed_before or ''}",
            f"provider_scorecard_test_delta_failed_after: {scorecard.test_delta_failed_after or ''}",
            f"provider_scorecard_test_delta_outcome: {scorecard.test_delta_outcome or ''}",
        ]

        # Modellauswahl-Metadaten hinzufügen
        if model_selection_metadata:
            summary_lines.extend([
                "",
                "model_selection:",
                f"  model: {model_selection_metadata.get('model', '')}",
                f"  reason: {model_selection_metadata.get('reason', '')}",
                f"  category: {model_selection_metadata.get('category', '')}",
                f"  risk: {model_selection_metadata.get('risk', '')}",
                f"  cost_tier: {model_selection_metadata.get('cost_tier', '')}",
                f"  fallback_plan: {', '.join(model_selection_metadata.get('fallback_plan', []))}",
            ])
        if cleanup_command:
            summary_lines.append(f"cleanup_command: {cleanup_command}")
            summary_lines.extend([
                "",
                preserved_worktree_recovery_note(Path(preserved_value), report.branch, base_branch),
            ])
        if note:
            summary_lines.extend(["", f"note: {note}"])
        if worker_result is not None:
            summary_lines.extend(["", "Der vollstaendige Worker-Output liegt in worker-output.log."])
        if git_change_summary:
            summary_lines.extend(["", "git_diff_stat:", *git_change_summary])
        if opencode_diagnostic_lines:
            summary_lines.extend(["", "opencode_runtime:", *opencode_diagnostic_lines])
        if output_tail:
            summary_lines.extend(["", "output_tail:", output_tail])
        if vibe_snippet:
            summary_lines.extend(["", "vibe_log_snippet:", vibe_snippet])
        # Ressourcen-Diagnosen im Summary nur bei Befunden
        if resource_diagnostics and resource_diagnostics.has_findings:
            from solver_run_resources import format_resource_diagnostics_summary_lines
            resource_summary = format_resource_diagnostics_summary_lines(resource_diagnostics)
            if resource_summary:
                summary_lines.extend(["", *resource_summary])

        (report.path / "summary.txt").write_text(
            "\n".join(summary_lines) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        print_warn(f"Run-Report konnte nicht gespeichert werden: {exc}")
        return None
    return report.path


def write_worker_diagnostics(result, repo: str, issue_number: int,
                              model: str, branch: str = "",
                              issue_title: str = "",
                              pr_url: str | None = None,
                              status: str = "worker_finished",
                              model_selection_metadata: dict | None = None,
                              test_command: str | None = None,
                              test_result: str | None = None,
                              test_delta_passed_before: int | None = None,
                              test_delta_passed_after: int | None = None,
                              test_delta_failed_before: int | None = None,
                              test_delta_failed_after: int | None = None,
                              test_delta_outcome: str | None = None) -> Path | None:
    report = create_run_report(repo, issue_number, branch, model, issue_title=issue_title)
    if not report:
        return None
    return write_run_report(
        report, status,
        worker_result=result,
        pr_url=pr_url,
        model_selection_metadata=model_selection_metadata,
        test_command=test_command,
        test_result=test_result,
        test_delta_passed_before=test_delta_passed_before,
        test_delta_passed_after=test_delta_passed_after,
        test_delta_failed_before=test_delta_failed_before,
        test_delta_failed_after=test_delta_failed_after,
        test_delta_outcome=test_delta_outcome,
    )


def cleanup_preserved_worktrees(root: Path = PRESERVED_WORKTREES_ROOT,
                                retention_days: int = PRESERVED_WORKTREE_RETENTION_DAYS,
                                dry_run: bool = True,
                                now_fn=time.time) -> list[Path]:
    if not root.exists():
        return []

    cutoff = now_fn() - max(retention_days, 0) * 24 * 60 * 60
    stale_paths: list[Path] = []
    for path in sorted(item for item in root.iterdir() if item.is_dir()):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime <= cutoff:
            stale_paths.append(path)
            if not dry_run:
                shutil.rmtree(path)
    return stale_paths
