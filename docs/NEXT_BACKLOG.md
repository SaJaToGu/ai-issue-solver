# Next Backlog

> **📌 Sprachhinweis / Language Note:**
> Diese Datei bleibt bewusst auf Englisch, da sie als Vorlage für GitHub Issues dient
> und von KI-Workern verarbeitet wird. Siehe [Sprachrichtlinie](LANGUAGE_POLICY.md)
> This file remains in English as it serves as a template for GitHub Issues and is
> processed by AI workers. See [Language Policy](LANGUAGE_POLICY.md)

This backlog captures the next technical ai-issue-solver provider phase.
Private personal ideas belong in the separate private `guido-project-lab`
repository and must not be added here.

Create selected items as GitHub issues with:

```bash
python scripts/create_backlog_issues.py --backlog docs/NEXT_BACKLOG.md
python scripts/create_backlog_issues.py --backlog docs/NEXT_BACKLOG.md --apply --confirm-create
```

Clean up completed items after their GitHub issues are closed with:

```bash
python scripts/cleanup_backlog.py --backlog docs/NEXT_BACKLOG.md
python scripts/cleanup_backlog.py --backlog docs/NEXT_BACKLOG.md --apply --confirm-remove
```

## 1. Add OpenRouter as a central cloud model provider

Labels: `setup`, `automation`, `workflow`

Priority: `high`

Add first-class OpenRouter support as a central cloud model provider so the
solver can reach multiple hosted models through one account and one key.

Suggested scope:
- add secret-safe configuration for `OPENROUTER_API_KEY`
- document key setup and recommended model names
- wire OpenRouter into the existing worker/model configuration with minimal
  abstraction
- keep existing providers working unchanged
- include preflight output that clearly explains missing credentials
- target solver PRs at `develop`

Open questions:
- Which default model should be recommended first?
- Should OpenRouter use the existing aider path, a direct API path, or a provider
  profile abstraction?
- Should cost/budget notes be required before enabling batch runs?

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`

## 2. Harden OpenCode install and auth preflight

Labels: `setup`, `automation`, `workflow`

Priority: `high`

Make the existing `opencode` worker adapter practical for daily use by improving
installation, authentication, and diagnostic behavior.

Suggested scope:
- add a clear install/auth preflight for `opencode`
- document install and login steps
- add a diagnostic command or dry-run path that confirms OpenCode is available
  before worker execution
- add model-name examples for OpenCode usage
- ensure worker failures produce useful run reports
- target solver PRs at `develop`

Open questions:
- Which OpenCode provider/login path should be the primary one?
- Should OpenCode become the recommended fallback for nested Codex failures?
- Do we want OpenCode runs marked differently in the dashboard?

Checks:
- `git diff --check`
- `python -m unittest discover -s tests`
