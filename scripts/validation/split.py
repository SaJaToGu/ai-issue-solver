from __future__ import annotations

import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from validation.git_notes import add_sub_issues_to_note
from validation.metrics import is_oversized, load_thresholds
from validation.split_client import SplitGitHubClient


SUB_ISSUE_LABELS = ["kind/refactor", "priority/2", "area/runs"]
MANUAL_REVIEW_LOC = 1000


def group_files_by_module(
    files: list[dict[str, Any]],
) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for f in files:
        path = f["filename"]
        if path.startswith("scripts/validation/"):
            groups["scripts/validation"].append(path)
        elif path.startswith("scripts/"):
            rest = path[len("scripts/"):]
            if "/" in rest:
                top = rest.split("/")[0]
                groups[f"scripts/{top}"].append(path)
            else:
                groups["scripts"].append(path)
        elif path.startswith("tests/validation/"):
            groups["tests/validation"].append(path)
        elif path.startswith("tests/"):
            rest = path[len("tests/"):]
            if "/" in rest:
                top = rest.split("/")[0]
                groups[f"tests/{top}"].append(path)
            else:
                groups["tests"].append(path)
        else:
            parts = path.split("/")
            top = parts[0] if len(parts) > 1 else path
            groups[top].append(path)
    return dict(groups)


def build_sub_issue_body(
    parent_pr: int,
    group_name: str,
    file_list: list[str],
    report_path: str | None = None,
) -> str:
    lines = [
        f"Decomposed from parent PR #{parent_pr}.",
        f"",
        f"Original PR: #{parent_pr}",
        f"Subset: {group_name}",
        f"",
        f"Files:",
    ]
    for f in file_list:
        lines.append(f"- `{f}`")
    lines.append("")
    lines.append(
        "Parent PR was oversized (>500 LOC). "
        "See validation report for context."
    )
    if report_path:
        lines.append(f"Report: {report_path}")
    return "\n".join(lines)


def decompose_pr_to_sub_issues(
    client: SplitGitHubClient,
    repo: str,
    pr_number: int,
    close_parent: bool = False,
    report_path: str | None = None,
    thresholds: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pr = client.get_pull_request(repo, pr_number)
    if pr is None:
        raise ValueError(f"PR #{pr_number} not found in {repo}")

    threshold_vals = load_thresholds(thresholds)
    pr_files_data = client.get_pr_files(repo, pr_number)
    total_loc = sum(f.changes for f in pr_files_data)
    total_files = len(pr_files_data)

    if not is_oversized(total_loc, total_files, 0.0, threshold_vals):
        return {
            "pr_number": pr_number,
            "is_oversized": False,
            "total_loc": total_loc,
            "total_files": total_files,
            "sub_issues": [],
            "skipped_reason": "PR is not oversized",
        }

    file_dicts = [{"filename": f.filename, "changes": f.changes} for f in pr_files_data]
    groups = group_files_by_module(file_dicts)

    sub_issues: list[dict[str, Any]] = []
    manual_review_files: list[str] = []

    for group_name, file_list in groups.items():
        big_files = [f for f in file_list if _changes_for_file(file_dicts, f) > MANUAL_REVIEW_LOC]
        if big_files:
            manual_review_files.extend(big_files)
            continue

        title = f"Decomposed from #{pr_number}: {group_name}"
        body = build_sub_issue_body(pr_number, group_name, file_list, report_path)
        created = client.create_issue(repo, title, body, SUB_ISSUE_LABELS)
        sub_issues.append({
            "number": created.get("number"),
            "title": title,
            "html_url": created.get("html_url", ""),
            "files": file_list,
        })
        print(f"  Created sub-issue #{created.get('number')}: {group_name}")

    if manual_review_files:
        print(
            f"  Manual review suggested for files >{MANUAL_REVIEW_LOC} LOC:",
            file=sys.stderr,
        )
        for f in manual_review_files:
            print(f"    - {f}", file=sys.stderr)

    result = {
        "pr_number": pr_number,
        "is_oversized": True,
        "total_loc": total_loc,
        "total_files": total_files,
        "sub_issues": sub_issues,
        "manual_review_files": manual_review_files,
    }

    note_data = [
        {"number": s["number"], "title": s["title"], "url": s["html_url"]}
        for s in sub_issues
    ]
    try:
        add_sub_issues_to_note(pr_number, note_data)
    except RuntimeError as exc:
        print(f"  Warning: git note not written ({exc})", file=sys.stderr)

    return result


def close_parent_with_cross_ref(
    client: SplitGitHubClient,
    repo: str,
    pr_number: int,
    sub_issue_numbers: list[int],
    comment: str | None = None,
) -> dict[str, Any]:
    pr = client.get_pull_request(repo, pr_number)
    if pr is None:
        raise ValueError(f"PR #{pr_number} not found in {repo}")

    if comment is None:
        sub_refs = ", ".join(f"#{n}" for n in sub_issue_numbers)
        comment = (
            f"Closed: decomposed into {sub_refs} "
            f"via the backward-split loop."
        )

    client.create_comment(repo, pr_number, comment)
    client.close_issue(repo, pr_number)
    print(f"  Closed PR #{pr_number} with cross-reference comment.")
    return {"pr_number": pr_number, "comment": comment}


def _changes_for_file(file_dicts: list[dict[str, Any]], filename: str) -> int:
    for f in file_dicts:
        if f["filename"] == filename:
            return f.get("changes", 0)
    return 0
