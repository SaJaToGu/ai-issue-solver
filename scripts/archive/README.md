# Archive

This directory holds **superseded or no-longer-maintained** scripts that were
moved here to stop being discoverable as current tools.

## Current contents

- `run_repolens_docker.sh` (moved 2026-06-23) — Docker sandbox wrapper for
  RepoLens static analysis
- `import_repolens_results.py` (moved 2026-06-23) — Importer for RepoLens
  Markdown reports → GitHub issues

See Issue #406 for the archive rationale (image no longer maintained in
this repo's ecosystem).

## Reviving

**Do not move files back without first opening a tracking issue that
documents:**

1. Where the `repolens` Docker image comes from (registry + tag)
2. Build pipeline (Dockerfile or upstream repo)
3. Why revival is needed now
4. CI check that the image is pullable