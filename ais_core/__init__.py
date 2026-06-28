"""ais_core — pure-library core for AIS (ai-issue-solver) v0.10.0+.

This package holds the stable library surface that backs the AIS CLI
(`ais_cli/`) and any future front-ends (MCP server, Codex skills,
Odysseus integration). Modules here are designed to be importable
without side-effects so they can be reused from multiple entry points.

Modules:
    repo_resolve   — resolve a repo hint to (owner, repo, remote, local_path)
    issue_resolve  — locate and inspect GitHub issues
    secret_filter  — redact tokens / keys / high-entropy strings
    json_contract  — canonical success/error envelope for AIS outputs
    run_state      — run-id generation and per-run state persistence
"""

__version__ = "0.9.0"

__all__ = ["__version__"]