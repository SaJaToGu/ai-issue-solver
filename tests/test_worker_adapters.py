"""
Tests für die Worker-Adapter (Issue #197).

Abgedeckte Szenarien:
- WorkerAdapter-Protokoll / Basisklasse
- CodexAdapter: build_command, build_env, Rate-Limit-Erkennung, run()
- OpenCodeAdapter: build_command, build_env, Prompt-Vorbereitung, run()
- MistralVibeAdapter: build_command, build_env, Vibe-Log-Snippet, run()
- AiderAdapter: build_command, build_env, Target-Inferenz, run()
- OpenRouterDirectAdapter: build_command, build_env, run()
- get_worker_adapter(): Factory-Funktion
- Konsistente Outcome-Klassifizierung über alle Adapter

Kein Test ruft echte Provider-APIs oder CLIs auf.
"""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, patch as mock_patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))


# ─────────────────────────────────────────────────────────────
# Hilfsfunktionen
# ─────────────────────────────────────────────────────────────

def _make_fake_subprocess_result(returncode: int = 0, output: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=output, stderr="")


# ─────────────────────────────────────────────────────────────
# Basis-Protokoll / WorkerAdapter
# ─────────────────────────────────────────────────────────────

class TestWorkerAdapterBase(unittest.TestCase):
    """Tests für das WorkerAdapter-Protokoll und die Basisklasse."""

    def test_base_adapter_is_abstract(self):
        """WorkerAdapter kann nicht direkt instanziiert werden."""
        from workers.base import WorkerAdapter
        with self.assertRaises(TypeError):
            WorkerAdapter()

    def test_worker_run_result_is_frozen(self):
        """WorkerRunResult ist unveränderlich (frozen dataclass)."""
        from workers.base import WorkerRunResult
        result = WorkerRunResult(returncode=0, output="ok")
        with self.assertRaises(Exception):
            result.returncode = 1  # type: ignore[misc]

    def test_worker_outcome_is_frozen(self):
        """WorkerOutcome ist unveränderlich (frozen dataclass)."""
        from workers.base import WorkerOutcome
        outcome = WorkerOutcome(should_continue=True, has_changes=True, reason="changed")
        with self.assertRaises(Exception):
            outcome.reason = "other"  # type: ignore[misc]

    def test_worker_validation_is_frozen(self):
        """WorkerValidation ist unveränderlich (frozen dataclass)."""
        from workers.base import WorkerValidation
        v = WorkerValidation(ok=True)
        with self.assertRaises(Exception):
            v.ok = False  # type: ignore[misc]

    def test_adapter_diagnostics_mutable(self):
        """AdapterDiagnostics ist veränderlich und kann Ausgaben sammeln."""
        from workers.base import AdapterDiagnostics
        diag = AdapterDiagnostics()
        diag.all_outputs.append("line 1")
        diag.vibe_log_snippet = "snippet"
        diag.rate_limit_note = "retry"
        self.assertEqual(diag.all_outputs, ["line 1"])
        self.assertEqual(diag.vibe_log_snippet, "snippet")
        self.assertEqual(diag.rate_limit_note, "retry")


# ─────────────────────────────────────────────────────────────
# CodexAdapter
# ─────────────────────────────────────────────────────────────

class TestCodexAdapter(unittest.TestCase):
    """Tests für den Codex-Worker-Adapter."""

    def test_codex_adapter_display_name(self):
        from workers.codex_adapter import CodexAdapter
        adapter = CodexAdapter()
        self.assertEqual(adapter.get_display_name(), "Codex CLI")

    def test_codex_adapter_name_attribute(self):
        from workers.codex_adapter import CodexAdapter
        self.assertEqual(CodexAdapter.name, "codex")

    def test_build_command_includes_exec_and_sandbox(self):
        from workers.codex_adapter import CodexAdapter
        with patch("workers.codex_adapter.find_codex_executable", return_value="/usr/bin/codex"):
            adapter = CodexAdapter(sandbox_mode="workspace-write")
            cmd = adapter.build_command("Fix issue", "/tmp/repo")

        self.assertIn("exec", cmd)
        self.assertIn("--sandbox", cmd)
        self.assertIn("workspace-write", cmd)
        self.assertIn("--cd", cmd)
        self.assertIn("/tmp/repo", cmd)
        self.assertIn("Fix issue", cmd)

    def test_build_command_includes_model_name_when_provided(self):
        from workers.codex_adapter import CodexAdapter
        with patch("workers.codex_adapter.find_codex_executable", return_value="/usr/bin/codex"):
            adapter = CodexAdapter()
            cmd = adapter.build_command("Fix", "/tmp/repo", model_name="gpt-4o")

        self.assertIn("--model", cmd)
        self.assertIn("gpt-4o", cmd)

    def test_build_command_includes_additional_dirs(self):
        from workers.codex_adapter import CodexAdapter
        with patch("workers.codex_adapter.find_codex_executable", return_value="/usr/bin/codex"):
            adapter = CodexAdapter()
            cmd = adapter.build_command("Fix", "/tmp/repo", additional_dirs=["/tmp/extra"])

        self.assertIn("--add-dir", cmd)
        self.assertIn("/tmp/extra", cmd)

    def test_build_command_raises_when_codex_not_found(self):
        from workers.codex_adapter import CodexAdapter
        with patch("workers.codex_adapter.find_codex_executable", return_value=None):
            adapter = CodexAdapter()
            with self.assertRaises(FileNotFoundError):
                adapter.build_command("Fix", "/tmp/repo")

    def test_build_env_returns_copy_of_base_env(self):
        from workers.codex_adapter import CodexAdapter
        adapter = CodexAdapter()
        env = adapter.build_env({}, base_env={"KEEP": "1"})
        self.assertEqual(env["KEEP"], "1")

    def test_run_returns_failed_result_when_codex_not_found(self):
        from workers.codex_adapter import CodexAdapter
        with patch("workers.codex_adapter.find_codex_executable", return_value=None):
            adapter = CodexAdapter()
            result, diag = adapter.run("Fix", "/tmp/repo", env={})

        self.assertEqual(result.returncode, 127)
        self.assertIn("nicht gefunden", result.output)
        self.assertEqual(len(diag.all_outputs), 1)

    def test_run_sets_rate_limit_note_when_deferred(self):
        """Mit defer_rate_limit=True wird Rate-Limit erkannt und Note gesetzt."""
        from workers.codex_adapter import CodexAdapter

        rate_limit_output = (
            "You have reached the Codex message limit\n"
            "Your rate limit will be reset on May 20, 2026, at 1:36 AM.\n"
        )

        fake_result = SimpleNamespace(
            returncode=1,
            output=rate_limit_output,
            last_activity_at=datetime.now(),
        )

        with patch("workers.codex_adapter.find_codex_executable", return_value="/usr/bin/codex"), \
             patch("workers.codex_adapter._run_subprocess", return_value=fake_result), \
             contextlib.redirect_stdout(io.StringIO()):
            adapter = CodexAdapter(defer_rate_limit=True)
            result, diag = adapter.run("Fix", "/tmp/repo", env={})

        self.assertIn("Batch-Runner", diag.rate_limit_note)

    def test_detect_codex_rate_limit_returns_none_for_clean_output(self):
        from workers.codex_adapter import detect_codex_rate_limit
        self.assertIsNone(detect_codex_rate_limit("Worker completed successfully."))

    def test_detect_codex_rate_limit_parses_reset_time(self):
        from workers.codex_adapter import detect_codex_rate_limit
        output = (
            "You have reached the Codex message limit\n"
            "Your rate limit will be reset on May 20, 2026, at 1:36 AM.\n"
        )
        rate_limit = detect_codex_rate_limit(output)
        self.assertIsNotNone(rate_limit)
        self.assertEqual(rate_limit.reset_at, datetime(2026, 5, 20, 1, 36))
        self.assertIn("May 20", rate_limit.reset_text)

    def test_sleep_until_codex_reset_sleeps_correct_duration(self):
        from workers.codex_adapter import CodexRateLimit, sleep_until_codex_reset
        sleeps = []
        rate_limit = CodexRateLimit(
            reset_at=datetime(2026, 5, 20, 1, 36),
            reset_text="May 20, 2026, at 1:36 AM",
        )
        with contextlib.redirect_stdout(io.StringIO()):
            sleep_until_codex_reset(
                rate_limit,
                sleep_fn=sleeps.append,
                now_fn=lambda: datetime(2026, 5, 20, 1, 35, 30),
            )
        self.assertEqual(sleeps, [30.0])

    def test_find_codex_executable_returns_none_when_missing(self):
        from workers.codex_adapter import find_codex_executable
        with patch("shutil.which", return_value=None), \
             patch("pathlib.Path.exists", return_value=False):
            result = find_codex_executable()
        self.assertIsNone(result)


# ─────────────────────────────────────────────────────────────
# OpenCodeAdapter
# ─────────────────────────────────────────────────────────────

class TestOpenCodeAdapter(unittest.TestCase):
    """Tests für den OpenCode-Worker-Adapter."""

    def test_opencode_adapter_display_name(self):
        from workers.opencode_adapter import OpenCodeAdapter
        adapter = OpenCodeAdapter()
        self.assertEqual(adapter.get_display_name(), "OpenCode CLI")

    def test_opencode_adapter_name_attribute(self):
        from workers.opencode_adapter import OpenCodeAdapter
        self.assertEqual(OpenCodeAdapter.name, "opencode")

    def test_build_command_includes_run_dir_and_model(self):
        from workers.opencode_adapter import OpenCodeAdapter
        with patch("workers.opencode_adapter.find_opencode_executable", return_value="/usr/bin/opencode"):
            adapter = OpenCodeAdapter()
            cmd = adapter.build_command("Fix issue", "/tmp/repo", model_name="gpt-4o")

        self.assertIn("run", cmd)
        self.assertIn("--dir", cmd)
        self.assertIn("/tmp/repo", cmd)
        self.assertIn("--model", cmd)
        self.assertIn("gpt-4o", cmd)
        # Letztes Argument ist der Prompt (mit Präambel)
        self.assertIn("repo-relative Pfade", cmd[-1])

    def test_build_command_prompt_includes_instructions(self):
        from workers.opencode_adapter import OpenCodeAdapter
        with patch("workers.opencode_adapter.find_opencode_executable", return_value="/usr/bin/opencode"):
            adapter = OpenCodeAdapter()
            cmd = adapter.build_command("Fix the bug", "/tmp/repo")

        self.assertIn("OpenCode wurde bereits mit `--dir`", cmd[-1])
        self.assertIn("Fix the bug", cmd[-1])

    def test_build_command_raises_when_opencode_not_found(self):
        from workers.opencode_adapter import OpenCodeAdapter
        with patch("workers.opencode_adapter.find_opencode_executable", return_value=None):
            adapter = OpenCodeAdapter()
            with self.assertRaises(FileNotFoundError):
                adapter.build_command("Fix", "/tmp/repo")

    def test_build_env_removes_github_tokens(self):
        from workers.opencode_adapter import OpenCodeAdapter
        adapter = OpenCodeAdapter()
        env = adapter.build_env(
            {},
            base_env={
                "GITHUB_TOKEN": "secret-token",
                "GH_TOKEN": "other-token",
                "KEEP": "1",
            },
        )
        self.assertNotIn("GITHUB_TOKEN", env)
        self.assertNotIn("GH_TOKEN", env)
        self.assertEqual(env["KEEP"], "1")

    def test_build_env_sets_solver_local_opencode_cache_only(self):
        from workers.opencode_adapter import OpenCodeAdapter
        adapter = OpenCodeAdapter()
        env = adapter.build_env({}, base_env={})
        self.assertIn("OPENCODE_CACHE_DIR", env)
        self.assertNotIn("OPENCODE_STATE_DIR", env)
        self.assertNotIn("OPENCODE_AUTH_FILE", env)

    def test_build_env_removes_xdg_state_home(self):
        from workers.opencode_adapter import OpenCodeAdapter
        adapter = OpenCodeAdapter()
        env = adapter.build_env({}, base_env={"XDG_STATE_HOME": "/tmp/opencode-state"})
        self.assertNotIn("XDG_STATE_HOME", env)

    def test_run_returns_failed_result_when_opencode_not_found(self):
        from workers.opencode_adapter import OpenCodeAdapter
        with patch("workers.opencode_adapter.find_opencode_executable", return_value=None):
            adapter = OpenCodeAdapter()
            result, diag = adapter.run("Fix", "/tmp/repo", env={})

        self.assertEqual(result.returncode, 127)
        self.assertIn("nicht gefunden", result.output)

    def test_find_opencode_executable_uses_repo_venv(self):
        from workers.opencode_diagnostics import find_opencode_executable
        with tempfile.TemporaryDirectory() as tmpdir:
            opencode = Path(tmpdir) / ".venv" / "bin" / "opencode"
            opencode.parent.mkdir(parents=True)
            opencode.write_text("#!/bin/sh\n", encoding="utf-8")
            opencode.chmod(0o755)
            inactive_python = str(Path(tmpdir) / "bin" / "python")

            with patch("workers.opencode_diagnostics.sys.executable", inactive_python):
                found = find_opencode_executable(tmpdir)

        self.assertEqual(found, str(opencode))

    def test_find_opencode_executable_uses_home_opencode_install(self):
        from workers.opencode_diagnostics import find_opencode_executable
        with tempfile.TemporaryDirectory() as tmpdir:
            home_opencode = Path(tmpdir) / ".opencode" / "bin" / "opencode"
            home_opencode.parent.mkdir(parents=True)
            home_opencode.write_text("#!/bin/sh\n", encoding="utf-8")
            home_opencode.chmod(0o755)

            with patch("workers.opencode_diagnostics.Path.home", return_value=Path(tmpdir)), \
                 patch("workers.opencode_diagnostics.shutil.which", return_value=None):
                found = find_opencode_executable("/missing/repo")

        self.assertEqual(found, str(home_opencode))

    def test_opencode_prompt_removes_github_tokens_from_env(self):
        """Adapter-Umgebung enthält keine GitHub-Tokens."""
        from workers.opencode_adapter import OpenCodeAdapter
        adapter = OpenCodeAdapter()
        env = adapter.build_env(
            {},
            base_env={"GITHUB_TOKEN": "ghp_secret", "GH_TOKEN": "gh_secret"},
        )
        self.assertNotIn("GITHUB_TOKEN", env)
        self.assertNotIn("GH_TOKEN", env)

    def test_ensure_solver_directories_creates_xdg_state(self):
        """ensure_solver_directories respektiert XDG_STATE_HOME."""
        from workers.opencode_adapter import ensure_solver_directories
        import os as _os
        original_env = _os.environ.copy()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                _os.environ["XDG_STATE_HOME"] = tmpdir
                _os.environ.pop("XDG_CACHE_HOME", None)
                state_dir, cache_dir = ensure_solver_directories()
                self.assertTrue(state_dir.exists())
                self.assertTrue(str(state_dir).startswith(tmpdir))
        finally:
            _os.environ.clear()
            _os.environ.update(original_env)


# ─────────────────────────────────────────────────────────────
# MistralVibeAdapter
# ─────────────────────────────────────────────────────────────

class TestMistralVibeAdapter(unittest.TestCase):
    """Tests für den Mistral Vibe CLI Adapter."""

    def test_mistral_vibe_adapter_display_name(self):
        from workers.mistral_vibe_adapter import MistralVibeAdapter
        adapter = MistralVibeAdapter()
        self.assertEqual(adapter.get_display_name(), "Mistral Vibe CLI")

    def test_mistral_vibe_adapter_name_attribute(self):
        from workers.mistral_vibe_adapter import MistralVibeAdapter
        self.assertEqual(MistralVibeAdapter.name, "mistral-vibe")

    def test_build_command_includes_workdir_prompt_and_limits(self):
        from workers.mistral_vibe_adapter import MistralVibeAdapter
        with patch("workers.mistral_vibe_adapter.find_vibe_executable", return_value="/usr/bin/vibe"):
            adapter = MistralVibeAdapter(max_turns=12, output_format="json")
            cmd = adapter.build_command("Fix issue", "/tmp/repo")

        self.assertEqual(cmd[0], "/usr/bin/vibe")
        self.assertIn("--workdir", cmd)
        self.assertIn("/tmp/repo", cmd)
        self.assertIn("--trust", cmd)
        self.assertIn("-p", cmd)
        self.assertIn("Fix issue", cmd)
        self.assertIn("--max-turns", cmd)
        self.assertIn("12", cmd)
        self.assertIn("--output", cmd)
        self.assertIn("json", cmd)

    def test_build_command_raises_when_vibe_not_found(self):
        from workers.mistral_vibe_adapter import MistralVibeAdapter
        with patch("workers.mistral_vibe_adapter.find_vibe_executable", return_value=None):
            adapter = MistralVibeAdapter()
            with self.assertRaises(FileNotFoundError):
                adapter.build_command("Fix", "/tmp/repo")

    def test_build_env_requires_mistral_api_key(self):
        from workers.mistral_vibe_adapter import MistralVibeAdapter
        adapter = MistralVibeAdapter()
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed), self.assertRaises(SystemExit) as raised:
            adapter.build_env({"MISTRAL_API_KEY": "sk-placeholder-HIER"}, base_env={})
        self.assertEqual(raised.exception.code, 1)

    def test_build_env_exports_mistral_api_key(self):
        from workers.mistral_vibe_adapter import MistralVibeAdapter
        adapter = MistralVibeAdapter()
        env = adapter.build_env({"MISTRAL_API_KEY": "real-key"}, base_env={"KEEP": "1"})
        self.assertEqual(env["MISTRAL_API_KEY"], "real-key")
        self.assertEqual(env["KEEP"], "1")

    def test_build_env_removes_opencode_vars(self):
        from workers.mistral_vibe_adapter import MistralVibeAdapter
        adapter = MistralVibeAdapter()
        env = adapter.build_env(
            {"MISTRAL_API_KEY": "real-key"},
            base_env={"OPENCODE_AUTH_FILE": "/tmp/auth.json", "KEEP": "1"},
        )
        self.assertNotIn("OPENCODE_AUTH_FILE", env)
        self.assertEqual(env["KEEP"], "1")

    def test_run_collects_vibe_log_snippet(self):
        """run() sammelt Vibe-Log-Snippet aus dem Adapter-Diagnostics."""
        from workers.mistral_vibe_adapter import MistralVibeAdapter

        fake_result = SimpleNamespace(
            returncode=0,
            output="Vibe completed.",
            last_activity_at=datetime.now(),
        )

        with tempfile.TemporaryDirectory() as repo_dir:
            # Vibe-Log erstellen
            log_dir = Path(repo_dir) / ".vibe" / "logs"
            log_dir.mkdir(parents=True)
            (log_dir / "vibe.log").write_text("Plan: analyse issue\nResult: done\n", encoding="utf-8")

            with patch("workers.mistral_vibe_adapter.find_vibe_executable", return_value="/usr/bin/vibe"), \
                 patch("workers.mistral_vibe_adapter._run_subprocess", return_value=fake_result), \
                 contextlib.redirect_stdout(io.StringIO()):
                adapter = MistralVibeAdapter()
                result, diag = adapter.run("Fix", repo_dir, env={"MISTRAL_API_KEY": "key"})

        self.assertGreater(len(diag.vibe_log_snippet), 0)

    def test_find_vibe_executable_uses_repo_venv(self):
        from workers.mistral_vibe_adapter import find_vibe_executable
        with tempfile.TemporaryDirectory() as tmpdir:
            vibe = Path(tmpdir) / ".venv" / "bin" / "vibe"
            vibe.parent.mkdir(parents=True)
            vibe.write_text("#!/bin/sh\n", encoding="utf-8")
            vibe.chmod(0o755)

            found = find_vibe_executable(tmpdir)

        self.assertEqual(found, str(vibe))

    def test_vibe_turn_limit_re_matches_event(self):
        """VIBE_TURN_LIMIT_RE erkennt das Turn-Limit-Ereignis."""
        from workers.mistral_vibe_adapter import VIBE_TURN_LIMIT_RE
        self.assertIsNotNone(VIBE_TURN_LIMIT_RE.search(
            "<vibe_stop_event>Turn limit of 30 reached</vibe_stop_event>"
        ))
        self.assertIsNone(VIBE_TURN_LIMIT_RE.search("Worker finished normally."))

    def test_run_returns_failed_result_when_vibe_not_found(self):
        from workers.mistral_vibe_adapter import MistralVibeAdapter
        with patch("workers.mistral_vibe_adapter.find_vibe_executable", return_value=None):
            adapter = MistralVibeAdapter()
            result, diag = adapter.run("Fix", "/tmp/repo", env={})
        self.assertEqual(result.returncode, 127)
        self.assertIn("nicht gefunden", result.output)


# ─────────────────────────────────────────────────────────────
# AiderAdapter
# ─────────────────────────────────────────────────────────────

class TestAiderAdapter(unittest.TestCase):
    """Tests für den Aider-basierten Worker-Adapter."""

    def test_aider_adapter_known_providers(self):
        from workers.aider_adapter import AiderAdapter
        for provider in ("claude", "openai", "mistral", "ollama", "openrouter"):
            with self.subTest(provider=provider):
                adapter = AiderAdapter(provider=provider)
                self.assertEqual(adapter.provider, provider)

    def test_aider_adapter_unknown_provider_raises(self):
        from workers.aider_adapter import AiderAdapter
        with self.assertRaises(ValueError):
            AiderAdapter(provider="unknown-provider")

    def test_aider_adapter_display_names(self):
        from workers.aider_adapter import AiderAdapter
        expected = {
            "claude": "Anthropic Claude (claude-sonnet-4-20250514)",
            "openai": "OpenAI GPT-4o",
            "mistral": "Mistral AI Magistral (magistral-medium-2509)",
            "ollama": "Ollama (lokal)",
            "openrouter": "OpenRouter (aider, legacy)",
        }
        for provider, name in expected.items():
            with self.subTest(provider=provider):
                self.assertEqual(AiderAdapter(provider=provider).get_display_name(), name)

    def test_aider_adapter_default_model_names(self):
        from workers.aider_adapter import AiderAdapter
        self.assertEqual(AiderAdapter("mistral").get_default_model_name(), "magistral-medium-2509")
        self.assertEqual(AiderAdapter("ollama").get_default_model_name(), "deepseek-coder:6.7b")
        self.assertEqual(AiderAdapter("openrouter").get_default_model_name(), "openrouter/openai/gpt-4o-mini")
        self.assertEqual(AiderAdapter("claude").get_default_model_name(), "")

    def test_build_command_claude_uses_model_flag(self):
        from workers.aider_adapter import AiderAdapter
        with patch("workers.aider_adapter.find_aider_executable", return_value="/usr/bin/aider"):
            adapter = AiderAdapter("claude")
            cmd = adapter.build_command("Fix", "/tmp/repo", file_targets=[])

        self.assertIn("--model", cmd)
        self.assertIn("claude-sonnet-4-20250514", cmd)
        self.assertIn("--message", cmd)
        self.assertIn("Fix", cmd)

    def test_build_command_mistral_interpolates_model_name(self):
        from workers.aider_adapter import AiderAdapter
        with patch("workers.aider_adapter.find_aider_executable", return_value="/usr/bin/aider"):
            adapter = AiderAdapter("mistral")
            cmd = adapter.build_command("Fix", "/tmp/repo", model_name="magistral-small-2509",
                                        file_targets=[])

        self.assertIn("mistral/magistral-small-2509", cmd)

    def test_build_command_includes_no_auto_commits_and_no_analytics(self):
        from workers.aider_adapter import AiderAdapter
        with patch("workers.aider_adapter.find_aider_executable", return_value="/usr/bin/aider"):
            adapter = AiderAdapter("claude")
            cmd = adapter.build_command("Fix", "/tmp/repo", file_targets=[])

        self.assertIn("--no-auto-commits", cmd)
        self.assertIn("--no-analytics", cmd)
        self.assertIn("--no-check-update", cmd)
        self.assertIn("--no-gitignore", cmd)
        self.assertIn("--map-tokens", cmd)
        self.assertIn("0", cmd)
        self.assertIn("--subtree-only", cmd)

    def test_build_command_uses_solver_local_history_files(self):
        from workers.aider_adapter import AiderAdapter
        with patch("workers.aider_adapter.find_aider_executable", return_value="/usr/bin/aider"):
            adapter = AiderAdapter("claude")
            cmd = adapter.build_command("Fix", "/tmp/repo", file_targets=[])

        self.assertIn("--chat-history-file", cmd)
        self.assertIn("--input-history-file", cmd)
        # Dateipfade sollten nicht im Repo-Verzeichnis liegen
        history_idx = cmd.index("--chat-history-file")
        chat_history = cmd[history_idx + 1]
        self.assertNotIn("/tmp/repo", chat_history)

    def test_build_command_raises_when_aider_not_found(self):
        from workers.aider_adapter import AiderAdapter
        with patch("workers.aider_adapter.find_aider_executable", return_value=None):
            adapter = AiderAdapter("claude")
            with self.assertRaises(FileNotFoundError):
                adapter.build_command("Fix", "/tmp/repo")

    def test_build_env_claude_requires_anthropic_key(self):
        from workers.aider_adapter import AiderAdapter
        adapter = AiderAdapter("claude")
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed), self.assertRaises(SystemExit) as raised:
            adapter.build_env({"ANTHROPIC_API_KEY": "sk-placeholder"}, base_env={})
        self.assertEqual(raised.exception.code, 1)

    def test_build_env_claude_exports_anthropic_key(self):
        from workers.aider_adapter import AiderAdapter
        adapter = AiderAdapter("claude")
        env = adapter.build_env({"ANTHROPIC_API_KEY": "real-key"}, base_env={})
        self.assertEqual(env["ANTHROPIC_API_KEY"], "real-key")

    def test_build_env_mistral_exports_mistral_key(self):
        from workers.aider_adapter import AiderAdapter
        adapter = AiderAdapter("mistral")
        env = adapter.build_env({"MISTRAL_API_KEY": "real-key"}, base_env={})
        self.assertEqual(env["MISTRAL_API_KEY"], "real-key")

    def test_build_env_openai_exports_openai_key(self):
        from workers.aider_adapter import AiderAdapter
        adapter = AiderAdapter("openai")
        env = adapter.build_env({"OPENAI_API_KEY": "real-key"}, base_env={})
        self.assertEqual(env["OPENAI_API_KEY"], "real-key")

    def test_build_env_openrouter_removes_other_provider_keys(self):
        from workers.aider_adapter import AiderAdapter
        adapter = AiderAdapter("openrouter")
        env = adapter.build_env(
            {"OPENROUTER_API_KEY": "real-key"},
            base_env={
                "ANTHROPIC_API_KEY": "anthropic",
                "MISTRAL_API_KEY": "mistral",
                "OPENAI_API_KEY": "openai",
                "GITHUB_TOKEN": "github",
            },
        )
        self.assertEqual(env["OPENROUTER_API_KEY"], "real-key")
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("MISTRAL_API_KEY", env)
        self.assertNotIn("OPENAI_API_KEY", env)
        # GITHUB_TOKEN bleibt für Git-Operationen
        self.assertEqual(env["GITHUB_TOKEN"], "github")

    def test_build_env_ollama_sets_api_base(self):
        from workers.aider_adapter import AiderAdapter
        adapter = AiderAdapter("ollama")
        env = adapter.build_env(
            {"OLLAMA_HOST": "http://custom:11434"},
            base_env={},
        )
        self.assertEqual(env["OLLAMA_API_BASE"], "http://custom:11434")

    def test_build_env_ollama_uses_default_host_when_not_configured(self):
        from workers.aider_adapter import AiderAdapter
        adapter = AiderAdapter("ollama")
        env = adapter.build_env({}, base_env={})
        self.assertEqual(env["OLLAMA_API_BASE"], "http://localhost:11434")

    def test_build_env_removes_opencode_vars(self):
        from workers.aider_adapter import AiderAdapter
        adapter = AiderAdapter("claude")
        env = adapter.build_env(
            {"ANTHROPIC_API_KEY": "key"},
            base_env={"OPENCODE_AUTH_FILE": "/tmp/auth.json", "OPENCODE_STATE_DIR": "/tmp/state"},
        )
        self.assertNotIn("OPENCODE_AUTH_FILE", env)
        self.assertNotIn("OPENCODE_STATE_DIR", env)

    def test_run_returns_failed_when_aider_not_found(self):
        from workers.aider_adapter import AiderAdapter
        with patch("workers.aider_adapter.find_aider_executable", return_value=None):
            adapter = AiderAdapter("claude")
            result, diag = adapter.run("Fix", "/tmp/repo", env={})
        self.assertEqual(result.returncode, 127)
        self.assertIn("nicht gefunden", result.output)

    def test_run_collects_output_in_diagnostics(self):
        from workers.aider_adapter import AiderAdapter

        fake_result = SimpleNamespace(
            returncode=0,
            output="Aider completed the fix.",
            last_activity_at=datetime.now(),
        )

        with patch("workers.aider_adapter.find_aider_executable", return_value="/usr/bin/aider"), \
             patch("workers.aider_adapter._run_subprocess", return_value=fake_result):
            adapter = AiderAdapter("claude")
            result, diag = adapter.run("Fix", "/tmp/repo", env={}, file_targets=[])

        self.assertEqual(result.returncode, 0)
        self.assertIn("Aider completed", diag.all_outputs[0])

    def test_aider_emits_deprecation_warning_on_init(self):
        """AiderAdapter.__init__ must emit a DeprecationWarning pointing at
        opencode / openrouter_direct / codex as the supported paths."""
        import warnings

        from workers.aider_adapter import AiderAdapter
        import workers.aider_adapter as aider_mod

        # Reset the once-per-process guard so the warning fires reliably in
        # this test even if an earlier test in the same process already
        # instantiated AiderAdapter.
        aider_mod._AIDER_DEPRECATION_EMITTED = False
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                AiderAdapter("claude")
            deprecation = [
                w for w in caught if issubclass(w.category, DeprecationWarning)
            ]
            self.assertEqual(
                len(deprecation), 1,
                "expected exactly one DeprecationWarning on AiderAdapter() init",
            )
            message = str(deprecation[0].message)
            self.assertIn("aider", message.lower())
            self.assertIn("opencode", message)
            self.assertIn("openrouter_direct", message)
            self.assertIn("codex", message)
        finally:
            # Restore the guard so the rest of the test run is not affected.
            aider_mod._AIDER_DEPRECATION_EMITTED = True


# ─────────────────────────────────────────────────────────────
# OpenRouterDirectAdapter
# ─────────────────────────────────────────────────────────────

class TestOpenRouterDirectAdapter(unittest.TestCase):
    """Tests für den OpenRouter Direct API Adapter."""

    def test_openrouter_direct_adapter_display_name(self):
        from workers.openrouter_direct_adapter import OpenRouterDirectAdapter
        adapter = OpenRouterDirectAdapter()
        self.assertEqual(adapter.get_display_name(), "OpenRouter (Direct)")

    def test_openrouter_direct_adapter_name_attribute(self):
        from workers.openrouter_direct_adapter import OpenRouterDirectAdapter
        self.assertEqual(OpenRouterDirectAdapter.name, "openrouter_direct")

    def test_build_command_returns_none(self):
        """OpenRouter Direct hat keinen CLI-Befehl."""
        from workers.openrouter_direct_adapter import OpenRouterDirectAdapter
        adapter = OpenRouterDirectAdapter()
        self.assertIsNone(adapter.build_command("Fix", "/tmp/repo"))

    def test_build_env_requires_openrouter_api_key(self):
        from workers.openrouter_direct_adapter import OpenRouterDirectAdapter
        adapter = OpenRouterDirectAdapter()
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed), self.assertRaises(SystemExit) as raised:
            adapter.build_env({"OPENROUTER_API_KEY": "sk-or-placeholder"}, base_env={})
        self.assertEqual(raised.exception.code, 1)

    def test_build_env_exports_openrouter_key(self):
        from workers.openrouter_direct_adapter import OpenRouterDirectAdapter
        adapter = OpenRouterDirectAdapter()
        env = adapter.build_env({"OPENROUTER_API_KEY": "real-key"}, base_env={})
        self.assertEqual(env["OPENROUTER_API_KEY"], "real-key")

    def test_build_env_removes_other_provider_keys(self):
        from workers.openrouter_direct_adapter import OpenRouterDirectAdapter
        adapter = OpenRouterDirectAdapter()
        env = adapter.build_env(
            {"OPENROUTER_API_KEY": "real-key"},
            base_env={
                "ANTHROPIC_API_KEY": "anthropic",
                "MISTRAL_API_KEY": "mistral",
                "OPENAI_API_KEY": "openai",
            },
        )
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("MISTRAL_API_KEY", env)
        self.assertNotIn("OPENAI_API_KEY", env)

    def test_build_env_removes_opencode_vars(self):
        from workers.openrouter_direct_adapter import OpenRouterDirectAdapter
        adapter = OpenRouterDirectAdapter()
        env = adapter.build_env(
            {"OPENROUTER_API_KEY": "key"},
            base_env={"OPENCODE_AUTH_FILE": "/tmp/auth.json", "KEEP": "1"},
        )
        self.assertNotIn("OPENCODE_AUTH_FILE", env)
        self.assertEqual(env["KEEP"], "1")

    def test_run_returns_error_when_api_key_missing(self):
        from workers.openrouter_direct_adapter import OpenRouterDirectAdapter
        adapter = OpenRouterDirectAdapter()
        clean_env = {k: v for k, v in os.environ.items() if k != "OPENROUTER_API_KEY"}

        with patch.dict(os.environ, clean_env, clear=True), \
             contextlib.redirect_stdout(io.StringIO()):
            result, diag = adapter.run("Fix", "/tmp/repo", env={})

        self.assertEqual(result.returncode, 1)
        self.assertIn("OPENROUTER_API_KEY", result.output)

    def test_run_uses_openrouter_worker_for_direct_api_call(self):
        """run() delegiert an workers.openrouter_worker.OpenRouterWorker."""
        from workers.openrouter_direct_adapter import OpenRouterDirectAdapter

        direct_result = SimpleNamespace(
            returncode=0,
            output="[openrouter_direct] 1 Patch angewendet.",
        )

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), \
             patch("workers.openrouter_worker.OpenRouterWorker") as worker_cls, \
             contextlib.redirect_stdout(io.StringIO()):
            worker_cls.return_value.run_direct.return_value = direct_result
            adapter = OpenRouterDirectAdapter()
            result, diag = adapter.run(
                "Fix issue",
                "/tmp/repo",
                env={"OPENROUTER_API_KEY": "test-key"},
                model_name="mistralai/mistral-large",
            )

        self.assertEqual(result.returncode, 0)
        self.assertIn("[openrouter_direct]", result.output)
        worker_cls.assert_called_once_with(
            api_key="test-key",
            model="mistralai/mistral-large",
            request_timeout_seconds=180.0,
            use_structured_output=False,
        )
        worker_cls.return_value.run_direct.assert_called_once_with(
            prompt="Fix issue",
            repo_dir="/tmp/repo",
            file_targets=[],
            max_tokens=8192,
            request_timeout=180.0,
        )

    def test_run_passes_explicit_file_targets_to_openrouter_worker(self):
        """OpenRouter Direct bekommt Datei-Targets als Prompt-Kontext."""
        from workers.openrouter_direct_adapter import OpenRouterDirectAdapter

        direct_result = SimpleNamespace(
            returncode=0,
            output="[openrouter_direct] 1 Patch angewendet.",
        )

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), \
             patch("workers.openrouter_worker.OpenRouterWorker") as worker_cls, \
             contextlib.redirect_stdout(io.StringIO()):
            worker_cls.return_value.run_direct.return_value = direct_result
            adapter = OpenRouterDirectAdapter()
            adapter.run(
                "Fix docs/SETUP_AIDER.md",
                "/tmp/repo",
                env={"OPENROUTER_API_KEY": "test-key"},
                file_targets=["docs/SETUP_AIDER.md"],
            )

        worker_cls.return_value.run_direct.assert_called_once_with(
            prompt="Fix docs/SETUP_AIDER.md",
            repo_dir="/tmp/repo",
            file_targets=["docs/SETUP_AIDER.md"],
            max_tokens=8192,
            request_timeout=180.0,
        )

    def test_run_returncode_2_for_prose_output(self):
        """Returncode 2 bei Prosa-Ausgabe ohne Diffs."""
        from workers.openrouter_direct_adapter import OpenRouterDirectAdapter

        direct_result = SimpleNamespace(
            returncode=2,
            output="[openrouter_direct] Keine Patches gefunden.",
        )

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), \
             patch("workers.openrouter_worker.OpenRouterWorker") as worker_cls, \
             contextlib.redirect_stdout(io.StringIO()):
            worker_cls.return_value.run_direct.return_value = direct_result
            adapter = OpenRouterDirectAdapter()
            result, diag = adapter.run("Fix", "/tmp/repo", env={"OPENROUTER_API_KEY": "test-key"})

        self.assertEqual(result.returncode, 2)

    def test_run_returncode_1_for_failed_patches(self):
        """Returncode 1 bei gefundenen aber fehlgeschlagenen Patches."""
        from workers.openrouter_direct_adapter import OpenRouterDirectAdapter

        direct_result = SimpleNamespace(
            returncode=1,
            output="[openrouter_direct] FEHLER: Alle Patches fehlgeschlagen.",
        )

        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}), \
             patch("workers.openrouter_worker.OpenRouterWorker") as worker_cls, \
             contextlib.redirect_stdout(io.StringIO()):
            worker_cls.return_value.run_direct.return_value = direct_result
            adapter = OpenRouterDirectAdapter()
            result, diag = adapter.run("Fix", "/tmp/repo", env={"OPENROUTER_API_KEY": "test-key"})

        self.assertEqual(result.returncode, 1)


# ─────────────────────────────────────────────────────────────
# get_worker_adapter() Factory-Funktion
# ─────────────────────────────────────────────────────────────

class TestGetWorkerAdapter(unittest.TestCase):
    """Tests für die get_worker_adapter() Factory-Funktion in solve_issues."""

    def test_factory_returns_codex_adapter(self):
        from solve_issues import get_worker_adapter
        from workers.codex_adapter import CodexAdapter
        adapter = get_worker_adapter("codex")
        self.assertIsInstance(adapter, CodexAdapter)

    def test_factory_returns_opencode_adapter(self):
        from solve_issues import get_worker_adapter
        from workers.opencode_adapter import OpenCodeAdapter
        adapter = get_worker_adapter("opencode")
        self.assertIsInstance(adapter, OpenCodeAdapter)

    def test_factory_returns_mistral_vibe_adapter(self):
        from solve_issues import get_worker_adapter
        from workers.mistral_vibe_adapter import MistralVibeAdapter
        adapter = get_worker_adapter("mistral-vibe")
        self.assertIsInstance(adapter, MistralVibeAdapter)

    def test_factory_returns_openrouter_direct_adapter(self):
        from solve_issues import get_worker_adapter
        from workers.openrouter_direct_adapter import OpenRouterDirectAdapter
        adapter = get_worker_adapter("openrouter_direct")
        self.assertIsInstance(adapter, OpenRouterDirectAdapter)

    def test_factory_returns_aider_adapter_for_claude(self):
        from solve_issues import get_worker_adapter
        from workers.aider_adapter import AiderAdapter
        adapter = get_worker_adapter("claude")
        self.assertIsInstance(adapter, AiderAdapter)
        self.assertEqual(adapter.provider, "claude")

    def test_factory_returns_aider_adapter_for_openai(self):
        from solve_issues import get_worker_adapter
        from workers.aider_adapter import AiderAdapter
        adapter = get_worker_adapter("openai")
        self.assertIsInstance(adapter, AiderAdapter)
        self.assertEqual(adapter.provider, "openai")

    def test_factory_returns_aider_adapter_for_mistral(self):
        from solve_issues import get_worker_adapter
        from workers.aider_adapter import AiderAdapter
        adapter = get_worker_adapter("mistral")
        self.assertIsInstance(adapter, AiderAdapter)
        self.assertEqual(adapter.provider, "mistral")

    def test_factory_returns_aider_adapter_for_ollama(self):
        from solve_issues import get_worker_adapter
        from workers.aider_adapter import AiderAdapter
        adapter = get_worker_adapter("ollama")
        self.assertIsInstance(adapter, AiderAdapter)
        self.assertEqual(adapter.provider, "ollama")

    def test_factory_returns_aider_adapter_for_openrouter(self):
        from solve_issues import get_worker_adapter
        from workers.aider_adapter import AiderAdapter
        adapter = get_worker_adapter("openrouter")
        self.assertIsInstance(adapter, AiderAdapter)
        self.assertEqual(adapter.provider, "openrouter")

    def test_factory_raises_for_unknown_model(self):
        from solve_issues import get_worker_adapter
        with self.assertRaises(ValueError):
            get_worker_adapter("nonexistent-model")


# ─────────────────────────────────────────────────────────────
# Konsistente Outcome-Klassifizierung
# ─────────────────────────────────────────────────────────────

class TestConsistentOutcomeClassification(unittest.TestCase):
    """
    Stellt sicher, dass die Outcome-Klassifizierung konsistent über alle
    Adapter und die gemeinsame shared primitive ist.

    Die Klassifizierung verwendet sowohl ``assess_worker_result()`` aus
    ``solve_issues`` (Legacy) als auch ``classify_worker_outcome()`` aus
    ``workers.execution`` (Shared), um sicherzustellen, dass beide denselben
    Code durchlaufen und identische Ergebnisse liefern.
    """

    def _assess(self, returncode: int, git_status: str, **kwargs):
        from solve_issues import WorkerRunResult, assess_worker_result
        result = WorkerRunResult(returncode=returncode, output="")
        return assess_worker_result(result, git_status, **kwargs)

    def _assess_shared(self, returncode: int, git_status: str, **kwargs):
        from workers.execution import classify_worker_outcome
        from workers.base import WorkerRunResult
        result = WorkerRunResult(returncode=returncode, output="")
        return classify_worker_outcome(result, git_status, **kwargs)

    def _assert_consistent(self, returncode: int, git_status: str,
                           expected_reason: str,
                           expected_continue: bool,
                           expected_changes: bool, **kwargs):
        legacy = self._assess(returncode, git_status, **kwargs)
        shared = self._assess_shared(returncode, git_status, **kwargs)
        for assessment in (legacy, shared):
            self.assertEqual(assessment.reason, expected_reason)
            self.assertEqual(assessment.should_continue, expected_continue)
            self.assertEqual(assessment.has_changes, expected_changes)

    def test_returncode_0_with_changes_is_changed(self):
        self._assert_consistent(0, " M README.md\n",
                                "changed", True, True)

    def test_returncode_0_without_changes_is_no_changes(self):
        self._assert_consistent(0, "",
                                "no_changes", False, False)

    def test_nonzero_with_meaningful_changes_continues(self):
        self._assert_consistent(1, " M scripts/solver.py\n",
                                "nonzero_with_changes", True, True)

    def test_nonzero_without_changes_stops(self):
        self._assert_consistent(1, "",
                                "nonzero_without_changes", False, False)

    def test_returncode_2_from_openrouter_direct_treated_as_nonzero(self):
        """OpenRouter Direct Returncode 2 (Prosa) wird als nonzero_without_changes klassifiziert."""
        self._assert_consistent(2, "",
                                "nonzero_without_changes", False, False)

    def test_returncode_2_with_changes_continues_for_review(self):
        """OpenRouter Direct Returncode 2 mit Änderungen: partial success."""
        self._assert_consistent(2, " M scripts/solver.py\n",
                                "nonzero_with_changes", True, True)

    def test_aider_side_effects_only_stops(self):
        """Nur Aider-Nebenwirkungen ohne Änderungen → stoppt."""
        self._assert_consistent(1, "?? .aider.chat.history.md\n",
                                "nonzero_without_changes", False, False)


# ─────────────────────────────────────────────────────────────
# Secret-Behandlung über Adapter-Grenzen hinweg
# ─────────────────────────────────────────────────────────────

class TestAdapterSecretHandling(unittest.TestCase):
    """Stellt sicher, dass Secrets korrekt behandelt werden."""

    def test_opencode_adapter_never_exposes_github_token(self):
        from workers.opencode_adapter import OpenCodeAdapter
        adapter = OpenCodeAdapter()
        env = adapter.build_env(
            {},
            base_env={"GITHUB_TOKEN": "ghp_secret123", "KEEP": "yes"},
        )
        for value in env.values():
            self.assertNotIn("ghp_secret123", str(value))

    def test_openrouter_direct_adapter_never_leaks_other_keys(self):
        from workers.openrouter_direct_adapter import OpenRouterDirectAdapter
        adapter = OpenRouterDirectAdapter()
        env = adapter.build_env(
            {"OPENROUTER_API_KEY": "or-key"},
            base_env={
                "ANTHROPIC_API_KEY": "sk-ant-secret",
                "MISTRAL_API_KEY": "ms-secret",
                "OPENAI_API_KEY": "sk-openai-secret",
            },
        )
        for value in env.values():
            self.assertNotIn("sk-ant-secret", str(value))
            self.assertNotIn("ms-secret", str(value))
            self.assertNotIn("sk-openai-secret", str(value))

    def test_aider_openrouter_adapter_does_not_keep_anthropic_key(self):
        from workers.aider_adapter import AiderAdapter
        adapter = AiderAdapter("openrouter")
        env = adapter.build_env(
            {"OPENROUTER_API_KEY": "or-key"},
            base_env={"ANTHROPIC_API_KEY": "sk-ant-secret"},
        )
        self.assertNotIn("ANTHROPIC_API_KEY", env)


if __name__ == "__main__":
    unittest.main()
