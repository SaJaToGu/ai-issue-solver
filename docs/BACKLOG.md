# Backlog

> **📌 Sprachhinweis / Language Note:**
> Diese Datei bleibt bewusst auf Englisch, da sie als Vorlage für GitHub Issues dient
> und von KI-Workern verarbeitet wird. Siehe [Sprachrichtlinie](LANGUAGE_POLICY.md)
> This file remains in English as it serves as a template for GitHub Issues and is
> processed by AI workers. See [Language Policy](LANGUAGE_POLICY.md)

This backlog captures the first issues for the `develop` workflow. These tasks
formed the first implementation round and are kept as project history. The next
planned work lives in [NEXT_BACKLOG.md](NEXT_BACKLOG.md).

Create them as GitHub issues with:

```bash
python scripts/create_backlog_issues.py
python scripts/create_backlog_issues.py --apply --confirm-create
```

## 1. Improve GitHub token setup and config validation

Labels: `setup`, `github`, `good-first-issue`

Make startup checks clearer for missing or invalid `GITHUB_TOKEN`, `GITHUB_USER`,
and optional AI worker credentials. The scripts should explain which file or
environment variable is expected and avoid exposing secret values.

## 2. Harden Codex worker mode

Labels: `codex`, `automation`

Test `solve_issues.py --model codex` against a small repository and make the
wrapper robust around Codex exit codes, no-op changes, and worker output.

## 3. Add a safe issue creation mode

Labels: `safety`, `github`

Require an explicit confirmation flag before creating real GitHub issues. Dry-run
should remain the recommended first step and should show enough detail to review
what would be created.

## 4. Improve analyzer findings

Labels: `analysis`, `quality`

Review the current analyzer checks and add more precise findings for project
metadata, stale repositories, missing tests, missing CI, and risky generated
files.

## 5. Add project workflow documentation

Labels: `documentation`, `workflow`

Document the branch model: `main` stays stable, `develop` collects work, feature
branches reference GitHub issues, and pull requests merge back into `develop`.
