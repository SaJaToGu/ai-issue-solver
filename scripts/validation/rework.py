from __future__ import annotations

import os
import sys
import time
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from validation.github_client import ValidationGitHubClient, ReviewThread
from validation.git_notes import add_rework_to_note
from validation.models import RunReportData
from solver_reporting import (
    RUN_REPORTS_ROOT,
    safe_run_repo_name,
    create_run_report,
    write_run_report,
)
from solver_repository import (
    CloneResult,
    clone_repo,
    checkout_existing_remote_branch,
    commit_and_push,
    git_status_porcelain,
    git_output,
)

# Resolve the prompt template path relative to the repo root, not the
# current working directory. The previous Path("prompts/rework_pr.md")
# broke whenever the CWD changed (e.g. inside run_pr_rework's tmpdir
# checkout) and the tests asserted against an absolute path.
_REPO_ROOT = Path(__file__).resolve().parents[2]
REWORK_PROMPT_PATH = _REPO_ROOT / "prompts" / "rework_pr.md"
REWORK_COMMIT_MESSAGE_PREFIX = "rework: apply review feedback"


def _load_rework_prompt_template() -> str:
    """Load the rework prompt template from ``prompts/rework_pr.md``."""
    path = REWORK_PROMPT_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"Rework prompt template not found: {path}. "
            "Create prompts/rework_pr.md or verify the path."
        )
    return path.read_text(encoding="utf-8")


def _build_rework_prompt(
    template: str,
    pr_number: int,
    owner: str,
    repo: str,
    base_branch: str,
    head_branch: str,
    diff: str,
    review_threads: list[ReviewThread],
) -> str:
    """Build the final rework prompt by filling in the template."""
    reviewer_usernames = ", ".join(
        sorted({t.user for t in review_threads})
    ) if review_threads else "unknown"

    thread_lines: list[str] = []
    for t in review_threads:
        path_info = f" in `{t.path}`" if t.path else ""
        thread_lines.append(f"- @{t.user}{path_info}: {t.body}")
    review_text = "\n".join(thread_lines) if thread_lines else "(no review comments found)"

    return template.format(
        pr_number=pr_number,
        owner=owner,
        repo=repo,
        base_branch=base_branch,
        head_branch=head_branch,
        reviewer_usernames=reviewer_usernames,
        diff=diff,
        review_threads=review_text,
    )


def _run_worker_via_subprocess(
    prompt: str,
    repo_dir: str,
    model: str,
    openrouter_key: str | None = None,
    timeout_seconds: float = 300,
) -> tuple[int, str]:
    """Run the OpenRouter direct worker as a subprocess with the given prompt.

    Uses the ``workers.openrouter_worker`` module to call the model and apply
    changes directly in the cloned repository.

    Returns (returncode, output_text).
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

    try:
        from workers.openrouter_worker import OpenRouterWorker, DirectRunResult
    except ImportError as exc:
        return (1, f"Worker import failed: {exc}")

    worker = OpenRouterWorker(
        api_key=openrouter_key,
        model=model,
        request_timeout_seconds=timeout_seconds,
        use_structured_output=True,
    )

    try:
        response_text, usage = worker.generate_with_usage(
            prompt=prompt,
            temperature=0.3,
            max_tokens=8192,
            timeout=timeout_seconds,
        )
    except Exception as exc:
        return (1, f"OpenRouter call failed: {exc}")

    patches = worker.extract_patches(response_text)
    if not patches:
        return (2, f"No patches found in model output.\n\n{response_text[:2000]}")

    result_lines: list[str] = []
    result_lines.append(f"Model response ({usage.model or 'unknown'}):")
    result_lines.append(response_text[:1000])
    result_lines.append("")

    applied_any = False
    for idx, patch_text in enumerate(patches):
        patch_results = worker.apply_patches(patch_text, repo_dir)
        for pr in patch_results:
            if pr.success:
                applied_any = True
                result_lines.append(f"  Applied patch {idx}: {pr.applied_file}")
            else:
                result_lines.append(f"  Failed patch {idx}: {pr.error or 'unknown'}")

    if not applied_any:
        return (3, "\n".join(result_lines) + "\nNo patches were applied successfully.")

    result_lines.append("")
    if usage.cost_usd is not None:
        result_lines.append(f"Cost: ${usage.cost_usd:.4f}")
    if usage.total_tokens:
        result_lines.append(f"Tokens: {usage.total_tokens} total")

    return (0, "\n".join(result_lines))


def run_pr_rework(
    owner: str,
    repo: str,
    pr_number: int,
    model: str = "mistralai/mistral-large",
    *,
    github_token: str | None = None,
    openrouter_key: str | None = None,
    dry_run: bool = False,
    base_branch_override: str | None = None,
    timeout_seconds: float = 300,
) -> RunReportData:
    """Run the rework workflow for a given PR number.

    Steps:
    1. Fetch PR info (head ref, base ref, state)
    2. Fetch PR diff and review threads
    3. Build the rework prompt
    4. Clone repo on the PR's head branch
    5. Run the worker with the rework prompt
    6. Commit and push follow-up commits
    7. Write run-report
    8. Update git notes

    Returns a :class:`RunReportData` with the outcome.
    """
    started_at = datetime.utcnow().isoformat()
    start_wall = time.monotonic()
    run_id = f"pr-{pr_number}-rework-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"

    if not github_token:
        github_token = os.getenv("GITHUB_TOKEN")
    if not github_token:
        return RunReportData(
            issue_number=pr_number,
            issue_title="",
            status="failed",
            error_class="config",
            error_detail="GITHUB_TOKEN not set",
            started_at=started_at,
            finished_at=datetime.utcnow().isoformat(),
            run_id=run_id,
        )

    client = ValidationGitHubClient(github_token, owner)

    # 1. Fetch PR info
    try:
        pr_info = client.get_pull_request(repo, pr_number)
    except RuntimeError as exc:
        return RunReportData(
            issue_number=pr_number,
            issue_title="",
            status="failed",
            error_class="api_error",
            error_detail=str(exc),
            started_at=started_at,
            finished_at=datetime.utcnow().isoformat(),
            run_id=run_id,
        )

    if pr_info is None:
        return RunReportData(
            issue_number=pr_number,
            issue_title="",
            status="failed",
            error_class="not_found",
            error_detail=f"PR #{pr_number} not found in {owner}/{repo}",
            started_at=started_at,
            finished_at=datetime.utcnow().isoformat(),
            run_id=run_id,
        )

    if pr_info.merged:
        return RunReportData(
            issue_number=pr_number,
            issue_title=pr_info.title,
            status="skip_merged_pr",
            pr_number=pr_number,
            pr_url=pr_info.html_url,
            error_class=None,
            error_detail="PR is already merged; rework skipped",
            started_at=started_at,
            finished_at=datetime.utcnow().isoformat(),
            run_id=run_id,
        )

    head_branch = pr_info.head_ref
    base_branch = base_branch_override or pr_info.base_ref

    if not head_branch:
        return RunReportData(
            issue_number=pr_number,
            issue_title=pr_info.title,
            status="failed",
            error_class="no_head_branch",
            error_detail=f"PR #{pr_number} has no head branch",
            started_at=started_at,
            finished_at=datetime.utcnow().isoformat(),
            run_id=run_id,
        )

    # 2. Fetch diff and review threads
    try:
        diff = client.get_pr_diff(repo, pr_number)
    except RuntimeError as exc:
        diff = f"(failed to fetch diff: {exc})"

    try:
        review_threads = client.get_pr_review_threads(repo, pr_number)
    except RuntimeError:
        review_threads = []

    # 3. Build prompt
    try:
        template = _load_rework_prompt_template()
    except FileNotFoundError as exc:
        return RunReportData(
            issue_number=pr_number,
            issue_title=pr_info.title,
            status="failed",
            error_class="config",
            error_detail=str(exc),
            started_at=started_at,
            finished_at=datetime.utcnow().isoformat(),
            run_id=run_id,
        )

    prompt = _build_rework_prompt(
        template=template,
        pr_number=pr_number,
        owner=owner,
        repo=repo,
        base_branch=base_branch,
        head_branch=head_branch,
        diff=diff,
        review_threads=review_threads,
    )

    # Dry-run: print metadata and prompt, return early
    if dry_run:
        duration = time.monotonic() - start_wall
        return RunReportData(
            issue_number=pr_number,
            issue_title=pr_info.title,
            status="dry_run",
            pr_number=pr_number,
            pr_url=pr_info.html_url,
            duration_seconds=duration,
            model=model,
            started_at=started_at,
            finished_at=datetime.utcnow().isoformat(),
            run_id=run_id,
        )

    if not openrouter_key:
        openrouter_key = os.getenv("OPENROUTER_API_KEY")
    if not openrouter_key:
        return RunReportData(
            issue_number=pr_number,
            issue_title=pr_info.title,
            status="failed",
            error_class="config",
            error_detail="OPENROUTER_API_KEY not set",
            started_at=started_at,
            finished_at=datetime.utcnow().isoformat(),
            run_id=run_id,
        )

    # 4. Clone repo on the PR's head branch
    tmpdir = tempfile.mkdtemp(prefix="ai-solver-rework-")
    repo_dir = os.path.join(tmpdir, repo)

    clone_result = clone_repo(owner, repo, github_token, repo_dir, head_branch)
    if not clone_result:
        return RunReportData(
            issue_number=pr_number,
            issue_title=pr_info.title,
            status="failed",
            error_class="clone_failed",
            error_detail=f"Could not clone {owner}/{repo} branch {head_branch}",
            started_at=started_at,
            finished_at=datetime.utcnow().isoformat(),
            run_id=run_id,
        )

    # Checkout the PR head branch (clone_repo uses base_branch, we need head)
    if not checkout_existing_remote_branch(repo_dir, head_branch):
        return RunReportData(
            issue_number=pr_number,
            issue_title=pr_info.title,
            status="failed",
            error_class="checkout_failed",
            error_detail=f"Could not checkout branch {head_branch}",
            started_at=started_at,
            finished_at=datetime.utcnow().isoformat(),
            run_id=run_id,
        )

    # 5. Run the worker
    returncode, worker_output = _run_worker_via_subprocess(
        prompt=prompt,
        repo_dir=repo_dir,
        model=model,
        openrouter_key=openrouter_key,
        timeout_seconds=timeout_seconds,
    )

    # 6. Commit and push
    status = "worker_failed"
    worker_error: str | None = None

    if returncode == 0:
        # Check for changes
        porcelain = git_status_porcelain(repo_dir)
        if porcelain.strip():
            commit_msg = f"{REWORK_COMMIT_MESSAGE_PREFIX} for PR #{pr_number}"
            pushed = commit_and_push(
                repo_dir, head_branch, commit_msg,
                github_token, owner, repo,
            )
            if pushed:
                status = "rework_pushed"
            else:
                status = "push_failed"
                worker_error = "Changes committed but push failed"
        else:
            status = "no_changes"
            worker_error = "Worker produced no changes"
    elif returncode == 2:
        status = "no_patches"
        worker_error = "Worker returned no parseable patches"
    elif returncode == 3:
        status = "patches_failed"
        worker_error = "Worker patches could not be applied"
    else:
        status = "worker_failed"
        worker_error = worker_output[:500] if worker_output else "Worker failed"

    # 7. Write run-report
    worker_result = type("WorkerResult", (), {
        "returncode": returncode,
        "output": worker_output,
        "last_activity_at": datetime.now(),
    })()

    report_path = RUN_REPORTS_ROOT / run_id
    report = create_run_report(
        repo, pr_number, head_branch, model,
        issue_title=pr_info.title,
        run_dir=str(report_path),
    )
    if report:
        git_changes = format_git_change_summary(repo_dir) if status == "rework_pushed" else None
        write_run_report(
            report,
            status,
            worker_result=worker_result,
            pr_url=pr_info.html_url,
            git_change_summary=git_changes,
            note=worker_error,
        )

    # 8. Update git notes
    try:
        rework_entry = {
            "run_id": run_id,
            "ts": datetime.utcnow().isoformat(),
            "status": status,
            "model": model,
            "pr": pr_number,
            "error": worker_error,
        }
        add_rework_to_note(pr_number, rework_entry)
    except RuntimeError:
        pass

    finished_at = datetime.utcnow().isoformat()
    duration = time.monotonic() - start_wall

    return RunReportData(
        issue_number=pr_number,
        issue_title=pr_info.title,
        status=status,
        pr_number=pr_number,
        pr_url=pr_info.html_url,
        duration_seconds=duration,
        model=model,
        error_class=worker_error.split(":")[0] if worker_error else None,
        error_detail=worker_error,
        started_at=started_at,
        finished_at=finished_at,
        run_id=run_id,
    )


def format_git_change_summary(repo_dir: str) -> list[str]:
    """Build a short summary of Git changes for the run-report."""
    porcelain = git_status_porcelain(repo_dir)
    lines = porcelain.strip().splitlines() if porcelain.strip() else []
    if not lines:
        return []
    summary = ["Git-Änderungen nach Rework:"]
    for line in lines[:20]:
        summary.append(f"  {line}")
    if len(lines) > 20:
        summary.append(f"  ... {len(lines) - 20} weitere Dateien")
    stat = git_output(repo_dir, ["diff", "--stat", "HEAD", "--"])
    if stat:
        for stat_line in stat.splitlines():
            summary.append(f"  {stat_line}")
    return summary
