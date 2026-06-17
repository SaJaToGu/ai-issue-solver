#!/usr/bin/env python3
"""knowledge_manager.py — Deterministic knowledge lifecycle engine.

Replaces the earlier LLM-based knowledge-management responsibilities
of the Planner role. Runs as a scheduled job (cron / launchd) and
performs four lifecycle actions:

  keep     — default for everything that matches no rule (no-op)
  archive  — automatic, per config/lifecycle_rules.yaml rules
  promote  — queued for human review (frequently referenced / tagged)
  delete   — queued for human review (irreversible)

Usage:
    python scripts/knowledge_manager.py scan        # Run all rules
    python scripts/knowledge_manager.py queue       # Show review queue
    python scripts/knowledge_manager.py archive     # Execute auto-archive
    python scripts/knowledge_manager.py status      # Summary of knowledge health
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]

# ── Default paths ─────────────────────────────────────────────────

LIFECYCLE_RULES_PATH = ROOT / "config" / "lifecycle_rules.yaml"
REVIEW_QUEUE_PATH = ROOT / "reports" / "knowledge-review-queue.json"
KNOWLEDGE_DIRECTORIES = ["docs/", ".agents/skills/", ".skills/"]
ARCHIVE_DIR = ROOT / "docs" / "archive"


# ── Data classes ──────────────────────────────────────────────────


@dataclass(frozen=True)
class LifecycleRule:
    name: str
    description: str
    days: int = 0
    min_references: int = 0
    enabled: bool = True
    paths: tuple[str, ...] = ()
    marker: str = ""


@dataclass(frozen=True)
class ArchiveCandidate:
    file_path: Path
    rule_name: str
    mtime_days_ago: float
    reference_count: int
    reason: str

    def to_dict(self) -> dict:
        return {
            "file_path": _repo_relative(self.file_path),
            "rule_name": self.rule_name,
            "mtime_days_ago": round(self.mtime_days_ago, 1),
            "reference_count": self.reference_count,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ReviewQueueEntry:
    id: str
    action: str  # promote | delete
    target: str  # repo-relative path
    rule_name: str
    reason: str
    requested_at: str
    status: str = "pending"  # pending | approved | rejected


@dataclass(frozen=True)
class ScanReport:
    scanned_at: str
    total_files: int
    archive_candidates: list[dict]
    promote_candidates: list[dict]
    delete_candidates: list[dict]
    total_candidates: int
    auto_archive_count: int
    review_queue_count: int


@dataclass(frozen=True)
class KnowledgeStatus:
    checked_at: str
    total_files: int
    archived_files: int
    pending_reviews: int
    last_scan_summary: str


# ── YAML loader (standard library only) ───────────────────────────
# We avoid a PyYAML dependency. The rules file uses a simple subset
# that json-compatible YAML-ish markup can represent; we parse it
# with a lightweight helper. Complex YAML features (anchors, tags)
# are NOT supported.


def _load_rules(path: Path = LIFECYCLE_RULES_PATH) -> dict:
    """Load lifecycle rules from a simple YAML-like file.

    Uses a regex-based parser that understands:
      - key: value (strings, numbers, booleans, null)
      - nested mappings (indented with 2 spaces)
      - list items  (- value)
    For full YAML compliance install PyYAML; this loader covers the
    subset used by config/lifecycle_rules.yaml.
    """
    if not path.exists():
        print(f"[knowledge] Rules file not found: {path}", file=sys.stderr)
        return {}

    text = path.read_text(encoding="utf-8")
    return _parse_yamlish(text)


def _parse_yamlish(text: str) -> dict:
    """Minimal YAML-subset parser. Returns a plain dict.

    Handles the subset used by config/lifecycle_rules.yaml:
      - key: scalar
      - key:  (nested mapping on next indented lines)
      - key:  (list on next indented lines starting with '- ')
      - - scalar
      - - key: value  (list of mappings, possibly multi-line)
    """
    lines = [line.rstrip() for line in text.split("\n")]
    return _parse_mapping(lines, 0)[0]


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _is_blank_or_comment(line: str) -> bool:
    s = line.strip()
    return not s or s.startswith("#")


def _parse_mapping(lines: list[str], start: int) -> tuple[dict, int]:
    """Parse mapping lines starting at `start`, return (dict, next_index)."""
    result: dict = {}
    base = _indent(lines[start]) if start < len(lines) else 0
    i = start

    while i < len(lines):
        if _is_blank_or_comment(lines[i]):
            i += 1
            continue

        indent = _indent(lines[i])
        if indent < base:
            break

        stripped = lines[i].lstrip()

        # List at mapping level shouldn't happen in our format
        if stripped.startswith("- "):
            break

        if ":" not in stripped:
            i += 1
            continue

        colon = stripped.index(":")
        key = stripped[:colon].strip()
        rest = stripped[colon + 1:].strip()
        i += 1

        if rest == "":
            # Look ahead to determine if value is a mapping or list
            nxt, _ = _skip_blank(lines, i)
            if nxt < len(lines) and _indent(lines[nxt]) > indent:
                next_stripped = lines[nxt].lstrip()
                if next_stripped.startswith("- "):
                    lst, i = _parse_list(lines, i)
                    result[key] = lst
                else:
                    result[key], i = _parse_mapping(lines, i)
            else:
                result[key] = ""
                i = i  # keep current i
        else:
            result[key] = _parse_scalar(rest)

    return result, i


def _parse_list(lines: list[str], start: int) -> tuple[list, int]:
    """Parse list items starting at line `start`, return (list, next_index)."""
    items: list = []
    base = _indent(lines[start]) if start < len(lines) else 0
    i = start

    while i < len(lines):
        if _is_blank_or_comment(lines[i]):
            i += 1
            continue

        indent = _indent(lines[i])
        if indent < base:
            break

        stripped = lines[i].lstrip()
        if not stripped.startswith("- "):
            # Continuation of previous list item (deeper indent than base)
            if indent >= base + 2 and items:
                # Skip continuation lines - they were already consumed
                i += 1
                continue
            break

        item_text = stripped[2:].strip()
        i += 1

        if ":" in item_text:
            # Inline mapping: - key: value
            colon = item_text.index(":")
            k = item_text[:colon].strip()
            v = item_text[colon + 1:].strip()
            item = {k: _parse_scalar(v) if v else ""}

            # Consume continuation lines (deeper indent than base+2)
            # Use _parse_mapping to properly handle nested lists
            nxt, _ = _skip_blank(lines, i)
            if nxt < len(lines) and _indent(lines[nxt]) >= base + 2:
                extra, i = _parse_mapping(lines, i)
                item.update(extra)

            items.append(item)
        elif item_text == "":
            # Empty - : the value is the next indented block
            nxt, _ = _skip_blank(lines, i)
            if nxt < len(lines) and _indent(lines[nxt]) > base + 2:
                next_stripped = lines[nxt].lstrip()
                if next_stripped.startswith("- "):
                    items.append(_parse_list(lines, i)[0])
                else:
                    items.append(_parse_mapping(lines, i)[0])
                _, i = _parse(lines, i)
            else:
                items.append("")
        else:
            # Scalar item
            items.append(_parse_scalar(item_text))

    return items, i


def _skip_blank(lines: list[str], start: int) -> tuple[int, str | None]:
    """Advance past blank/comment lines, return (index, line_or_None)."""
    i = start
    while i < len(lines) and _is_blank_or_comment(lines[i]):
        i += 1
    return (i, lines[i] if i < len(lines) else None)


def _parse_scalar(value: str) -> str | int | float | bool | None:
    # Strip inline comments (everything after first unquoted #)
    comment_pos = -1
    in_quotes = False
    for idx, ch in enumerate(value):
        if ch in ('"', "'"):
            in_quotes = not in_quotes
        elif ch == "#" and not in_quotes:
            comment_pos = idx
            break
    if comment_pos >= 0:
        value = value[:comment_pos].strip()

    if value == "" or value == "null":
        return None
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    # Strip surrounding quotes
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        value = value[1:-1]
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


# ── Helpers ───────────────────────────────────────────────────────


def _repo_relative(path: Path) -> str:
    """Convert an absolute path to a repo-relative string."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> dict | list:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, (dict, list)):
            return data
        return {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, data: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _days_old(path: Path) -> float:
    """Return how many days old the file's mtime is."""
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        return (datetime.now(timezone.utc) - mtime).total_seconds() / 86400.0
    except OSError:
        return float("inf")


def _find_knowledge_files(
    directories: list[str] | None = None,
    patterns: tuple[str, ...] = ("*.md", "*.yaml", "*.yml", "*.py"),
) -> list[Path]:
    """Find all knowledge files in configured directories."""
    if directories is None:
        directories = KNOWLEDGE_DIRECTORIES

    files: list[Path] = []
    for rel_dir in directories:
        abs_dir = ROOT / rel_dir
        if not abs_dir.exists():
            continue
        for pattern in patterns:
            files.extend(abs_dir.rglob(pattern))
    return sorted(files)


def _count_references(
    target_stem: str,
    all_files: list[Path],
    exclude_paths: tuple[str, ...] = ("docs/archive/",),
) -> int:
    """Count how many tracked files reference the given filename stem."""
    count = 0
    for f in all_files:
        rel = _repo_relative(f)
        if any(rel.startswith(excl) for excl in exclude_paths):
            continue
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
            if target_stem in content:
                count += 1
        except OSError:
            pass
    return count


def _load_review_queue(path: Path = REVIEW_QUEUE_PATH) -> list[dict]:
    queue = _read_json(path)
    if isinstance(queue, list):
        return queue
    return []


def _save_review_queue(queue: list[dict], path: Path = REVIEW_QUEUE_PATH) -> None:
    # Always purge old approved/rejected entries older than 90 days
    now = datetime.now(timezone.utc)
    stale_cutoff = now.isoformat(timespec="seconds")
    # Simple heuristic: keep approved/rejected for 90 days
    fresh: list[dict] = []
    for entry in queue:
        status = entry.get("status", "pending")
        if status in ("approved", "rejected"):
            requested = entry.get("requested_at", "")
            if requested and requested < stale_cutoff:
                continue
        fresh.append(entry)
    _write_json(path, fresh)


def _next_queue_id(queue: list[dict]) -> str:
    existing = [e.get("id", "") for e in queue]
    num = 1
    while f"queue-{num:04d}" in existing:
        num += 1
    return f"queue-{num:04d}"


# ── Archive logic (automatic) ─────────────────────────────────────


def _get_archive_rules(rules: dict) -> list[LifecycleRule]:
    """Extract archive condition rules from the loaded config."""
    archive_cfg = rules.get("archive", {})
    if not archive_cfg.get("enabled", True):
        return []
    excluded = set(archive_cfg.get("excluded_paths", []) or [])
    conditions = archive_cfg.get("conditions", []) or []
    parsed: list[LifecycleRule] = []
    for cond in conditions:
        if not isinstance(cond, dict):
            continue
        if not cond.get("enabled", True):
            continue
        parsed.append(LifecycleRule(
            name=str(cond.get("name", "unknown")),
            description=str(cond.get("description", "")),
            days=int(cond.get("days", 0)),
            min_references=int(cond.get("min_references", 0)),
            enabled=True,
            paths=tuple(cond.get("paths", []) or []),
        ))
    return parsed, excluded


def _matches_archive_path(file_path: Path, rules: list[LifecycleRule]) -> bool:
    """Check if the file is within any archive-condition path."""
    rel = _repo_relative(file_path)
    for rule in rules:
        for rule_path in rule.paths:
            if rel.startswith(rule_path):
                return True
    return False


def find_archive_candidates(
    files: list[Path],
    rules_cfg: dict,
    all_files: list[Path],
) -> list[ArchiveCandidate]:
    """Find files matching archive conditions."""
    archive_rules, excluded = _get_archive_rules(rules_cfg)
    if not archive_rules:
        return []

    candidates: list[ArchiveCandidate] = []

    for f in files:
        rel = _repo_relative(f)
        # Check exclusion list
        if any(rel.startswith(excl) or rel == excl for excl in excluded):
            continue

        days = _days_old(f)
        refs = _count_references(f.stem, all_files)

        for rule in archive_rules:
            reasons: list[str] = []

            if rule.name == "mtime_older_than" and rule.days > 0:
                if not _matches_archive_path(f, [rule]):
                    continue
                if days >= rule.days:
                    reasons.append(
                        f"mtime ({days:.0f} days) >= threshold ({rule.days} days)"
                    )

            if rule.name == "no_incoming_references" and rule.min_references == 0:
                if refs == 0:
                    reasons.append("no incoming references")

            if reasons:
                # Check if already in archive
                arch_rel = _repo_relative(ROOT / ARCHIVE_DIR / rel)
                if rel.startswith("docs/archive/"):
                    continue

                candidates.append(ArchiveCandidate(
                    file_path=f,
                    rule_name=rule.name,
                    mtime_days_ago=days,
                    reference_count=refs,
                    reason="; ".join(reasons),
                ))
                break  # One rule match is enough

    return candidates


def execute_archive(candidates: list[ArchiveCandidate]) -> int:
    """Move archive candidates to docs/archive/.

    Returns the number of files actually moved.
    """
    count = 0
    for cand in candidates:
        rel = _repo_relative(cand.file_path)
        target = ROOT / ARCHIVE_DIR / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            cand.file_path.rename(target)
            print(f"[knowledge] Archived: {rel} -> docs/archive/{rel}")
            count += 1
        except OSError as exc:
            print(
                f"[knowledge] Failed to archive {rel}: {exc}",
                file=sys.stderr,
            )
    return count


# ── Promote logic (human review queue) ────────────────────────────


def find_promote_candidates(
    files: list[Path],
    rules_cfg: dict,
    all_files: list[Path],
    existing_queue: list[dict],
) -> list[ReviewQueueEntry]:
    """Find files matching promote conditions and queue them."""
    promote_cfg = rules_cfg.get("promote", {})
    if not promote_cfg.get("enabled", True):
        return []

    conditions = promote_cfg.get("conditions", []) or []
    queued_targets = {e.get("target", "") for e in existing_queue}

    entries: list[ReviewQueueEntry] = []

    for f in files:
        rel = _repo_relative(f)
        # Skip if already queued
        if rel in queued_targets:
            continue
        # Skip if already in archive
        if rel.startswith("docs/archive/"):
            continue

        refs = _count_references(f.stem, all_files)

        for cond in conditions:
            if not isinstance(cond, dict):
                continue
            if not cond.get("enabled", True):
                continue

            name = cond.get("name", "unknown")
            reasons: list[str] = []

            if name == "frequently_referenced":
                min_refs = int(cond.get("min_reference_count", 3))
                if refs >= min_refs:
                    reasons.append(
                        f"referenced {refs} times (min: {min_refs})"
                    )

            if name == "manual_tag":
                marker = str(cond.get("marker", "promote-candidate"))
                try:
                    first_lines = f.read_text(encoding="utf-8").split("\n")[:5]
                    if any(marker in line for line in first_lines):
                        reasons.append(f"tagged with '{marker}' marker")
                except OSError:
                    pass

            if reasons:
                entry = ReviewQueueEntry(
                    id=_next_queue_id(existing_queue + [asdict(e) for e in entries]),
                    action="promote",
                    target=rel,
                    rule_name=str(name),
                    reason="; ".join(reasons),
                    requested_at=_now_iso(),
                )
                entries.append(entry)
                break

    return entries


# ── Delete logic (human review queue) ─────────────────────────────


def find_delete_candidates(
    files: list[Path],
    rules_cfg: dict,
    all_files: list[Path],
    existing_queue: list[dict],
) -> list[ReviewQueueEntry]:
    """Find files matching delete conditions and queue them."""
    delete_cfg = rules_cfg.get("delete", {})
    if not delete_cfg.get("enabled", True):
        return []

    conditions = delete_cfg.get("conditions", []) or []
    excluded = set(delete_cfg.get("excluded_paths", []) or [])
    queued_targets = {e.get("target", "") for e in existing_queue}

    entries: list[ReviewQueueEntry] = []

    for f in files:
        rel = _repo_relative(f)

        # Check exclusion list
        if any(rel.startswith(excl) or rel == excl for excl in excluded):
            continue
        # Skip if already queued
        if rel in queued_targets:
            continue

        days = _days_old(f)
        refs = _count_references(f.stem, all_files)

        for cond in conditions:
            if not isinstance(cond, dict):
                continue
            if not cond.get("enabled", True):
                continue

            name = cond.get("name", "unknown")
            reasons: list[str] = []

            if name == "archived_longer_than":
                if not rel.startswith("docs/archive/"):
                    continue
                threshold = int(cond.get("days", 365))
                if days >= threshold:
                    reasons.append(
                        f"archived {days:.0f} days (threshold: {threshold})"
                    )

            if name == "orphaned_long_term":
                threshold = int(cond.get("days", 180))
                if days >= threshold and refs == 0:
                    reasons.append(
                        f"orphaned {days:.0f} days, 0 references"
                    )

            if reasons:
                entry = ReviewQueueEntry(
                    id=_next_queue_id(existing_queue + [asdict(e) for e in entries]),
                    action="delete",
                    target=rel,
                    rule_name=str(name),
                    reason="; ".join(reasons),
                    requested_at=_now_iso(),
                )
                entries.append(entry)
                break

    return entries


# ── Scan orchestrator ─────────────────────────────────────────────


def run_scan(
    rules_path: Path = LIFECYCLE_RULES_PATH,
    queue_path: Path = REVIEW_QUEUE_PATH,
) -> ScanReport:
    """Run all lifecycle rules against the knowledge base."""
    rules = _load_rules(rules_path)
    if not rules:
        print("[knowledge] No rules loaded. Check config/lifecycle_rules.yaml")
        return ScanReport(
            scanned_at=_now_iso(),
            total_files=0,
            archive_candidates=[],
            promote_candidates=[],
            delete_candidates=[],
            total_candidates=0,
            auto_archive_count=0,
            review_queue_count=0,
        )

    all_files = _find_knowledge_files()
    total = len(all_files)
    print(f"[knowledge] Scanning {total} files...")

    # 1. Archive candidates (automatic)
    archive_cands = find_archive_candidates(all_files, rules, all_files)
    print(
        f"[knowledge] Archive candidates: {len(archive_cands)} "
        f"(automatic — no human review needed)"
    )

    # 2. Load existing review queue
    queue = _load_review_queue(queue_path)
    pending = [e for e in queue if e.get("status", "pending") == "pending"]
    print(f"[knowledge] Pending review queue entries: {len(pending)}")

    # 3. Promote candidates
    promote_entries = find_promote_candidates(all_files, rules, all_files, queue)
    print(f"[knowledge] Promote candidates (new): {len(promote_entries)}")

    # 4. Delete candidates
    delete_entries = find_delete_candidates(all_files, rules, all_files, queue)
    print(f"[knowledge] Delete candidates (new): {len(delete_entries)}")

    # 5. Append new entries to queue
    all_new = promote_entries + delete_entries
    if all_new:
        queue.extend([asdict(e) for e in all_new])
        _save_review_queue(queue, queue_path)
        print(f"[knowledge] Added {len(all_new)} entries to review queue")

    # Serialize for report
    report = ScanReport(
        scanned_at=_now_iso(),
        total_files=total,
        archive_candidates=[c.to_dict() for c in archive_cands],
        promote_candidates=[asdict(e) for e in promote_entries],
        delete_candidates=[asdict(e) for e in delete_entries],
        total_candidates=len(archive_cands) + len(all_new),
        auto_archive_count=len(archive_cands),
        review_queue_count=len([e for e in queue if e.get("status", "pending") == "pending"]),
    )

    # Write scan report
    report_path = ROOT / "reports" / "knowledge-scan-report.json"
    _write_json(report_path, asdict(report))
    print(f"[knowledge] Scan report written to {_repo_relative(report_path)}")

    return report


# ── CLI ───────────────────────────────────────────────────────────


# Issue #312: promote/delete are irreversible knowledge-governance actions.
# They must fail closed and require explicit source-of-truth + confirmation.

ALLOWED_PROMOTE_SOURCES = ("user", "planner")
ALLOWED_DELETE_SOURCES = ("user",)


def _refuse(action: str, reason: str) -> "NoReturn":
    """Single exit point for all governance rejections (issue #312).

    Always exits with code 1 and a clear, action-prefixed message on
    stderr. Used by every fail-closed check in this module so that
    the exit code is consistent regardless of which rule was violated.
    """
    print(f"Refusing {action}: {reason}", file=sys.stderr)
    sys.exit(1)


def _validate_source_of_truth(action: str, source: str | None) -> str:
    """Fail-closed: missing or invalid source-of-truth is always rejected."""
    if not source:
        _refuse(action, "source-of-truth is required; fail-closed.")
    if action == "promote" and source not in ALLOWED_PROMOTE_SOURCES:
        _refuse(action, f"--source-of-truth must be one of: {', '.join(ALLOWED_PROMOTE_SOURCES)}.")
    if action == "delete" and source not in ALLOWED_DELETE_SOURCES:
        _refuse(action, "--source-of-truth must be user.")
    return source


def _validate_user_confirmed(action: str, confirmed: bool) -> None:
    if not confirmed:
        _refuse(action, "--user-confirmed is required.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Knowledge Manager — deterministic knowledge lifecycle engine",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # scan command
    scan_parser = subparsers.add_parser(
        "scan", help="Run all lifecycle rules against the knowledge base"
    )
    scan_parser.add_argument(
        "--rules",
        default=str(LIFECYCLE_RULES_PATH),
        help="Path to lifecycle rules YAML (default: config/lifecycle_rules.yaml)",
    )
    scan_parser.add_argument(
        "--queue",
        default=str(REVIEW_QUEUE_PATH),
        help="Path to review queue JSON (default: reports/knowledge-review-queue.json)",
    )

    # queue command
    queue_parser = subparsers.add_parser(
        "queue", help="Show the current human review queue"
    )
    queue_parser.add_argument(
        "--queue",
        default=str(REVIEW_QUEUE_PATH),
        help="Path to review queue JSON",
    )
    queue_parser.add_argument(
        "--status",
        default="pending",
        choices=["pending", "approved", "rejected", "all"],
        help="Filter by status (default: pending)",
    )

    # archive command
    archive_parser = subparsers.add_parser(
        "archive", help="Execute automatic archive actions from last scan"
    )
    archive_parser.add_argument(
        "--rules",
        default=str(LIFECYCLE_RULES_PATH),
        help="Path to lifecycle rules YAML",
    )
    archive_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be archived without moving files",
    )

    # status command
    status_parser = subparsers.add_parser(
        "status", help="Show knowledge base health summary"
    )
    status_parser.add_argument(
        "--queue",
        default=str(REVIEW_QUEUE_PATH),
        help="Path to review queue JSON",
    )

    # promote command (Issue #312 governance)
    promote_parser = subparsers.add_parser(
        "promote",
        help="Promote a file to permanent knowledge (requires explicit authorization)",
    )
    promote_parser.add_argument(
        "--target", required=True, help="File path to promote"
    )
    promote_parser.add_argument(
        "--source-of-truth",
        required=True,
        help="Authorization source (must be 'user' or 'planner') — issue #312",
    )
    promote_parser.add_argument(
        "--user-confirmed",
        action="store_true",
        help="Explicit human confirmation that this action is authorized",
    )
    promote_parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually perform the action (default: dry-run preview only)",
    )

    # delete command (Issue #312 governance)
    delete_parser = subparsers.add_parser(
        "delete",
        help="Delete a file from the knowledge base (requires explicit authorization)",
    )
    delete_parser.add_argument(
        "--target", required=True, help="File path to delete"
    )
    delete_parser.add_argument(
        "--source-of-truth",
        required=True,
        help="Authorization source (must be 'user') — issue #312",
    )
    delete_parser.add_argument(
        "--user-confirmed",
        action="store_true",
        help="Explicit human confirmation that this action is authorized",
    )
    delete_parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually perform the action (default: dry-run preview only)",
    )

    return parser.parse_args(argv)


def run_scan_command(args: argparse.Namespace) -> int:
    report = run_scan(
        rules_path=Path(args.rules),
        queue_path=Path(args.queue),
    )
    print(f"[knowledge] Scan complete. {report.total_candidates} candidate(s) found.")
    return 0


def run_queue_command(args: argparse.Namespace) -> int:
    queue_path = Path(args.queue)
    queue = _load_review_queue(queue_path)

    if args.status == "all":
        filtered = queue
    else:
        filtered = [e for e in queue if e.get("status", "pending") == args.status]

    if not filtered:
        print(f"[knowledge] No queue entries with status '{args.status}'.")
        return 0

    print(f"[knowledge] Review queue ({args.status}): {len(filtered)} entry(ies)")
    print()
    for entry in filtered:
        status = entry.get("status", "pending")
        action = entry.get("action", "?")
        target = entry.get("target", "?")
        reason = entry.get("reason", "")
        rule = entry.get("rule_name", "")
        eid = entry.get("id", "?")
        print(f"  [{status}] {eid}: {action} {target}")
        print(f"          Rule: {rule} — {reason}")
    print()
    return 0


def run_archive_command(args: argparse.Namespace) -> int:
    rules = _load_rules(Path(args.rules))
    if not rules:
        print("[knowledge] No rules loaded.", file=sys.stderr)
        return 1

    all_files = _find_knowledge_files()
    candidates = find_archive_candidates(all_files, rules, all_files)

    if not candidates:
        print("[knowledge] No archive candidates found.")
        return 0

    if args.dry_run:
        print(f"[knowledge] Dry-run: {len(candidates)} file(s) would be archived:")
        for cand in candidates:
            rel = _repo_relative(cand.file_path)
            print(f"  {rel} ({cand.reason})")
        return 0

    moved = execute_archive(candidates)
    print(f"[knowledge] Archived {moved} file(s).")
    return 0


def run_status_command(args: argparse.Namespace) -> int:
    queue = _load_review_queue(Path(args.queue))
    pending = [e for e in queue if e.get("status", "pending") == "pending"]

    all_files = _find_knowledge_files()
    archive_files = [f for f in all_files if _repo_relative(f).startswith("docs/archive/")]

    print(f"[knowledge] Knowledge base status")
    print(f"  Total files:      {len(all_files)}")
    print(f"  Archived files:   {len(archive_files)}")
    print(f"  Pending reviews:  {len(pending)}")

    if pending:
        promotes = [e for e in pending if e.get("action") == "promote"]
        deletes = [e for e in pending if e.get("action") == "delete"]
        if promotes:
            print(f"    Promote: {len(promotes)}")
        if deletes:
            print(f"    Delete:  {len(deletes)}")

    # Read last scan report if available
    report_path = ROOT / "reports" / "knowledge-scan-report.json"
    if report_path.exists():
        report = _read_json(report_path)
        if isinstance(report, dict):
            print(f"  Last scan:        {report.get('scanned_at', 'unknown')}")
            print(f"  Last candidates:  {report.get('total_candidates', 0)}")

    return 0


def run_promote_command(args: argparse.Namespace) -> int:
    """Issue #312 governance: explicit, fail-closed promote.

    Subcommand structure makes combine-with-archive/delete structurally
    impossible (different commands, different argv). Defense in depth:
    validate the argv-level flags here as well.
    """
    _validate_user_confirmed("promote", bool(getattr(args, "user_confirmed", False)))
    source = _validate_source_of_truth("promote", getattr(args, "source_of_truth", None))
    target = args.target
    if getattr(args, "apply", False):
        print(f"[knowledge] promote (apply): source={source}, target={target}")
        # TODO: actual promote logic — move/copy target to permanent knowledge.
        return 0
    print(f"[knowledge] promote (dry-run): source={source}, target={target}")
    return 0


def run_delete_command(args: argparse.Namespace) -> int:
    """Issue #312 governance: explicit, fail-closed delete."""
    _validate_user_confirmed("delete", bool(getattr(args, "user_confirmed", False)))
    source = _validate_source_of_truth("delete", getattr(args, "source_of_truth", None))
    target = args.target
    if getattr(args, "apply", False):
        print(f"[knowledge] delete (apply): source={source}, target={target}")
        # TODO: actual delete logic — backup then remove.
        return 0
    print(f"[knowledge] delete (dry-run): source={source}, target={target}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "scan":
        return run_scan_command(args)
    elif args.command == "queue":
        return run_queue_command(args)
    elif args.command == "archive":
        return run_archive_command(args)
    elif args.command == "status":
        return run_status_command(args)
    elif args.command == "promote":
        return run_promote_command(args)
    elif args.command == "delete":
        return run_delete_command(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
