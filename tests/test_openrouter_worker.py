"""
Tests für den direkten OpenRouter Worker.

Abgedeckte Szenarien:
- Initialisierung mit und ohne API-Key
- Header-Konstruktion
- Erfolgreicher API-Aufruf (generate)
- API-Fehler
- Ungültige API-Antwort
- Patch-Extraktion aus Markdown-Code-Fences und nackten Diffs
- Erfolgreiche Patch-Anwendung (apply_patches)
- Malformierter/nicht anwendbarer Patch (apply_patches)
- Kompletter run_direct()-Durchlauf mit Erfolg
- run_direct() ohne auswertbare Diffs (Prosa-Ausgabe)
- run_direct() bei API-Fehler
- Fehlender OPENROUTER_API_KEY
"""

import os
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import tempfile

from workers.openrouter_worker import OpenRouterWorker, PatchResult, DirectRunResult


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _make_valid_diff(filename: str = "foo.py", old_line: str = "x = 1", new_line: str = "x = 2") -> str:
    """Erzeugt einen minimalen, syntaktisch korrekten Unified-Diff."""
    return textwrap.dedent(f"""\
        --- a/{filename}
        +++ b/{filename}
        @@ -1,1 +1,1 @@
        -{old_line}
        +{new_line}
    """)


# ---------------------------------------------------------------------------
# Klasse: Basis-Tests (init, headers, generate)
# ---------------------------------------------------------------------------

class TestOpenRouterWorkerInit(unittest.TestCase):
    """Tests für Initialisierung und Header-Konstruktion."""

    def test_init_with_api_key(self):
        """Normaler Konstruktor mit explizitem API-Key."""
        worker = OpenRouterWorker(api_key="test_key")
        self.assertEqual(worker.api_key, "test_key")
        self.assertEqual(worker.model, "mistralai/mistral-large")

    def test_init_missing_api_key_raises(self):
        """Fehlender API-Key löst ValueError aus."""
        with patch.dict(os.environ, {}, clear=True):
            # OPENROUTER_API_KEY aus Umgebung entfernen, falls vorhanden
            env_without_key = {k: v for k, v in os.environ.items() if k != "OPENROUTER_API_KEY"}
            with patch.dict(os.environ, env_without_key, clear=True):
                with self.assertRaises(ValueError) as ctx:
                    OpenRouterWorker(api_key=None)
                self.assertIn("OPENROUTER_API_KEY", str(ctx.exception))

    def test_init_from_env_var(self):
        """API-Key wird aus Umgebungsvariable gelesen."""
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "env_key"}):
            worker = OpenRouterWorker()
            self.assertEqual(worker.api_key, "env_key")

    def test_build_headers(self):
        """Header-Konstruktion enthält alle Pflichtfelder."""
        worker = OpenRouterWorker(api_key="test_api_key")
        headers = worker.build_headers()
        self.assertEqual(headers["Authorization"], "Bearer test_api_key")
        self.assertIn("Content-Type", headers)
        self.assertIn("HTTP-Referer", headers)
        self.assertIn("X-Title", headers)

    def test_build_headers_default_referer(self):
        """Standard-Referer zeigt auf das opencode-Repository."""
        worker = OpenRouterWorker(api_key="k")
        headers = worker.build_headers()
        self.assertIn("opencode", headers["HTTP-Referer"])

    def test_custom_model(self):
        """Benutzerdefiniertes Modell wird korrekt gesetzt."""
        worker = OpenRouterWorker(api_key="k", model="openai/gpt-4o")
        self.assertEqual(worker.model, "openai/gpt-4o")

    def test_build_patch_prompt_requires_unified_diff_only(self):
        """OpenRouter Direct wraps prompts with strict patch-only instructions."""
        worker = OpenRouterWorker(api_key="k")

        prompt = worker.build_patch_prompt("Fix docs/SETUP_AIDER.md")

        self.assertIn("Return ONLY one or more unified diff patches", prompt)
        self.assertIn("patch -p1", prompt)
        self.assertIn("--- a/<repo-relative-path>", prompt)
        self.assertIn("Do not include explanations", prompt)
        self.assertIn("Fix docs/SETUP_AIDER.md", prompt)


class TestOpenRouterWorkerFileContext(unittest.TestCase):
    """Tests für bounded Datei-Kontext im direkten OpenRouter-Prompt."""

    def setUp(self):
        self.worker = OpenRouterWorker(api_key="k")
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_file(self, rel_path: str, content: str) -> None:
        full_path = Path(self.tmpdir) / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")

    def test_build_file_context_includes_repo_relative_target(self):
        self._write_file("docs/SETUP_AIDER.md", "# Setup\n\nOpenRouter\n")

        context = self.worker.build_file_context(
            self.tmpdir,
            ["docs/SETUP_AIDER.md"],
        )

        self.assertIn("--- FILE: docs/SETUP_AIDER.md ---", context)
        self.assertIn("# Setup", context)
        self.assertIn("--- END FILE: docs/SETUP_AIDER.md ---", context)

    def test_build_file_context_ignores_missing_and_external_targets(self):
        self._write_file("docs/SETUP_AIDER.md", "# Setup\n")

        context = self.worker.build_file_context(
            self.tmpdir,
            ["missing.md", "../outside.md", "docs/SETUP_AIDER.md"],
        )

        self.assertIn("docs/SETUP_AIDER.md", context)
        self.assertNotIn("missing.md", context)
        self.assertNotIn("outside.md", context)


# ---------------------------------------------------------------------------
# Klasse: generate()-Tests
# ---------------------------------------------------------------------------

class TestOpenRouterWorkerGenerate(unittest.TestCase):
    """Tests für den direkten API-Aufruf."""

    def setUp(self):
        self.worker = OpenRouterWorker(api_key="test_api_key", model="mistralai/mistral-large")
        self.prompt = "Test prompt"

    @patch("requests.post")
    def test_generate_success(self, mock_post):
        """Erfolgreicher API-Aufruf gibt Modell-Antwort zurück."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Test response"}}]
        }
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        response = self.worker.generate(self.prompt)
        self.assertEqual(response, "Test response")
        mock_post.assert_called_once_with(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=self.worker.build_headers(),
            json={
                "model": "mistralai/mistral-large",
                "messages": [{"role": "user", "content": self.prompt}],
                "temperature": 0.7,
                "max_tokens": 4096,
            },
        )

    @patch("requests.post")
    def test_generate_api_error(self, mock_post):
        """API-Fehler wird als Exception weitergegeben."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("API Error")
        mock_post.return_value = mock_response

        with self.assertRaises(Exception):
            self.worker.generate(self.prompt)

    @patch("requests.post")
    def test_generate_invalid_response_no_choices(self, mock_post):
        """Ungültige Antwort ohne 'choices' löst ValueError aus."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"invalid": "response"}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        with self.assertRaises(ValueError) as ctx:
            self.worker.generate(self.prompt)
        self.assertIn("Ungültige Antwort", str(ctx.exception))

    @patch("requests.post")
    def test_generate_empty_choices(self, mock_post):
        """Leere 'choices'-Liste löst ValueError aus."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"choices": []}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        with self.assertRaises(ValueError):
            self.worker.generate(self.prompt)


# ---------------------------------------------------------------------------
# Klasse: extract_patches()-Tests
# ---------------------------------------------------------------------------

class TestExtractPatches(unittest.TestCase):
    """Tests für die Patch-Extraktion aus Modell-Output."""

    def setUp(self):
        self.worker = OpenRouterWorker(api_key="k")

    def test_extract_from_markdown_diff_fence(self):
        """Patch in ```diff ... ``` Fence wird erkannt."""
        diff = _make_valid_diff()
        text = f"Hier ist der Fix:\n\n```diff\n{diff}```\n\nFertig."
        patches = self.worker.extract_patches(text)
        self.assertEqual(len(patches), 1)
        self.assertIn("---", patches[0])
        self.assertIn("+++", patches[0])
        self.assertIn("@@", patches[0])

    def test_extract_from_plain_fence(self):
        """Patch in ``` ... ``` Fence (ohne 'diff') wird erkannt."""
        diff = _make_valid_diff()
        text = f"Fix:\n\n```\n{diff}```"
        patches = self.worker.extract_patches(text)
        self.assertEqual(len(patches), 1)

    def test_extract_bare_diff(self):
        """Nackter Unified-Diff ohne Fences wird erkannt."""
        diff = _make_valid_diff()
        text = f"Bitte diese Änderung vornehmen:\n\n{diff}\n\nDas war es."
        patches = self.worker.extract_patches(text)
        self.assertGreaterEqual(len(patches), 1)

    def test_extract_multiple_patches(self):
        """Mehrere Patches in einer Antwort werden alle extrahiert."""
        diff1 = _make_valid_diff("file1.py", "a = 1", "a = 2")
        diff2 = _make_valid_diff("file2.py", "b = 1", "b = 2")
        text = f"```diff\n{diff1}```\n\n```diff\n{diff2}```"
        patches = self.worker.extract_patches(text)
        self.assertEqual(len(patches), 2)

    def test_no_patch_in_prose(self):
        """Reine Prosa ohne Diff-Inhalt ergibt leere Liste."""
        text = "Das ist nur Prosa ohne Patches. Bitte manuell bearbeiten."
        patches = self.worker.extract_patches(text)
        self.assertEqual(patches, [])

    def test_no_patch_empty_string(self):
        """Leerer String ergibt leere Liste."""
        patches = self.worker.extract_patches("")
        self.assertEqual(patches, [])

    def test_malformed_fence_without_diff_headers(self):
        """Fence ohne --- / +++ Header wird nicht als gültiger Patch gewertet."""
        text = "```diff\nkein echter diff hier\nnur text\n```"
        patches = self.worker.extract_patches(text)
        self.assertEqual(patches, [])


# ---------------------------------------------------------------------------
# Klasse: apply_patches()-Tests
# ---------------------------------------------------------------------------

class TestApplyPatches(unittest.TestCase):
    """Tests für die Patch-Anwendung im Repository-Verzeichnis."""

    def setUp(self):
        self.worker = OpenRouterWorker(api_key="k")
        # Temporäres Verzeichnis als Mini-Repository
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_file(self, rel_path: str, content: str) -> None:
        """Schreibt eine Datei ins temporäre Verzeichnis."""
        full_path = Path(self.tmpdir) / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")

    def _read_file(self, rel_path: str) -> str:
        """Liest eine Datei aus dem temporären Verzeichnis."""
        return (Path(self.tmpdir) / rel_path).read_text(encoding="utf-8")

    def test_successful_patch_application(self):
        """Gültiger Patch wird korrekt angewendet."""
        self._write_file("foo.py", "x = 1\n")
        diff = _make_valid_diff("foo.py", "x = 1", "x = 2")
        results = self.worker.apply_patches([diff], self.tmpdir)

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].success, f"Patch fehlgeschlagen: {results[0].error}")
        self.assertEqual(self._read_file("foo.py"), "x = 2\n")

    def test_successful_patch_sets_applied_file(self):
        """Erfolgreich angewendeter Patch enthält den Dateinamen."""
        self._write_file("foo.py", "x = 1\n")
        diff = _make_valid_diff("foo.py", "x = 1", "x = 2")
        results = self.worker.apply_patches([diff], self.tmpdir)

        self.assertEqual(results[0].applied_file, "foo.py")

    def test_patch_with_wrong_hunk_counts_is_recounted(self):
        """git apply --recount repairs common LLM-generated hunk count mistakes."""
        self._write_file("foo.txt", "Intro\nOld\nTail\n")
        diff = textwrap.dedent("""\
            --- a/foo.txt
            +++ b/foo.txt
            @@ -1,3 +1,4 @@
             Intro
            -Old
            +New
            +Extra
             Tail
        """)

        results = self.worker.apply_patches([diff], self.tmpdir)

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].success, f"Patch fehlgeschlagen: {results[0].error}")
        self.assertEqual(self._read_file("foo.txt"), "Intro\nNew\nExtra\nTail\n")

    def test_malformed_patch_returns_failure(self):
        """Ungültiger Patch-Content führt zu einem fehlgeschlagenen PatchResult."""
        bad_patch = "--- a/nonexistent.py\n+++ b/nonexistent.py\n@@ -1,1 +1,1 @@\n-old\n+new\n"
        results = self.worker.apply_patches([bad_patch], self.tmpdir)

        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].success)
        self.assertIsNotNone(results[0].error)

    def test_malformed_patch_does_not_raise(self):
        """Fehlgeschlagene Patches werfen keine Exception."""
        bad_patch = "das ist kein gültiger patch\n"
        try:
            results = self.worker.apply_patches([bad_patch], self.tmpdir)
            # Kein Fehler erwartet — entweder success oder failure, aber keine Exception
        except Exception as exc:
            self.fail(f"apply_patches warf unerwartet: {exc}")

    def test_multiple_patches_partial_success(self):
        """Mehrere Patches: Erfolg und Fehler werden korrekt protokolliert."""
        self._write_file("good.py", "a = 1\n")
        good_diff = _make_valid_diff("good.py", "a = 1", "a = 2")
        bad_diff = "--- a/missing.py\n+++ b/missing.py\n@@ -1,1 +1,1 @@\n-old\n+new\n"

        results = self.worker.apply_patches([good_diff, bad_diff], self.tmpdir)

        self.assertEqual(len(results), 2)
        # Patch-Indizes stimmen
        self.assertEqual(results[0].patch_index, 1)
        self.assertEqual(results[1].patch_index, 2)
        # Erster Patch erfolgreich
        self.assertTrue(results[0].success)
        # Zweiter Patch fehlgeschlagen
        self.assertFalse(results[1].success)

    def test_empty_patch_list_returns_empty(self):
        """Leere Patch-Liste ergibt leere Ergebnis-Liste."""
        results = self.worker.apply_patches([], self.tmpdir)
        self.assertEqual(results, [])


# ---------------------------------------------------------------------------
# Klasse: run_direct()-Tests
# ---------------------------------------------------------------------------

class TestRunDirect(unittest.TestCase):
    """Tests für den vollständigen run_direct()-Durchlauf."""

    def setUp(self):
        self.worker = OpenRouterWorker(api_key="k", model="mistralai/mistral-large")
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_file(self, rel_path: str, content: str) -> None:
        full_path = Path(self.tmpdir) / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")

    @patch("requests.post")
    def test_run_direct_success(self, mock_post):
        """Erfolgreicher Durchlauf: Patch wird angewendet, returncode=0."""
        self._write_file("bar.py", "y = 10\n")
        diff = _make_valid_diff("bar.py", "y = 10", "y = 20")
        model_response = f"Hier ist der Fix:\n\n```diff\n{diff}```\n"

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": model_response}}]
        }
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        result = self.worker.run_direct("fix bar.py", self.tmpdir)

        self.assertEqual(result.returncode, 0)
        self.assertGreater(len(result.patch_results), 0)
        self.assertTrue(result.patch_results[0].success)
        # Datei wurde tatsächlich geändert
        content = (Path(self.tmpdir) / "bar.py").read_text(encoding="utf-8")
        self.assertEqual(content, "y = 20\n")

    @patch("requests.post")
    def test_run_direct_sends_patch_prompt_to_model(self, mock_post):
        """run_direct() must ask the model for raw unified diffs, not prose."""
        self._write_file("bar.py", "y = 10\n")
        diff = _make_valid_diff("bar.py", "y = 10", "y = 20")

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": f"```diff\n{diff}```"}}]
        }
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        self.worker.run_direct("fix bar.py", self.tmpdir)

        payload = mock_post.call_args.kwargs["json"]
        sent_prompt = payload["messages"][0]["content"]
        self.assertIn("Return ONLY one or more unified diff patches", sent_prompt)
        self.assertIn("fix bar.py", sent_prompt)

    @patch("requests.post")
    def test_run_direct_no_op_prose(self, mock_post):
        """Modell gibt nur Prosa zurück: returncode=2."""
        model_response = "Ich habe die Datei analysiert. Keine Änderungen notwendig."

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": model_response}}]
        }
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        result = self.worker.run_direct("analyse code", self.tmpdir)

        self.assertEqual(result.returncode, 2)
        self.assertIn("Prosa", result.output)
        self.assertEqual(result.raw_response, model_response)

    @patch("requests.post")
    def test_run_direct_malformed_patch(self, mock_post):
        """Modell gibt ungültigen Patch zurück: returncode=1."""
        # Ungültiger Patch: Datei existiert nicht im Verzeichnis
        bad_diff = "--- a/missing_file.py\n+++ b/missing_file.py\n@@ -1,1 +1,1 @@\n-old\n+new\n"
        model_response = f"```diff\n{bad_diff}```"

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": model_response}}]
        }
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        result = self.worker.run_direct("fix something", self.tmpdir)

        # Patch wurde erkannt, aber Anwendung fehlgeschlagen
        self.assertEqual(result.returncode, 1)
        self.assertGreater(len(result.patch_results), 0)
        self.assertFalse(result.patch_results[0].success)

    @patch("requests.post")
    def test_run_direct_api_error(self, mock_post):
        """API-Fehler führt zu returncode=1 ohne Exception."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("Connection refused")
        mock_post.return_value = mock_response

        result = self.worker.run_direct("test prompt", self.tmpdir)

        self.assertEqual(result.returncode, 1)
        self.assertIn("API-Fehler", result.output)
        self.assertEqual(result.raw_response, "")

    @patch("requests.post")
    def test_run_direct_output_contains_model_name(self, mock_post):
        """run_direct()-Output enthält den Modell-Namen zur Nachvollziehbarkeit."""
        model_response = "Keine Patches."
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": model_response}}]
        }
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        result = self.worker.run_direct("test", self.tmpdir)

        self.assertIn("mistralai/mistral-large", result.output)


# ---------------------------------------------------------------------------
# Klasse: Tests für fehlenden API-Key-Pfad
# ---------------------------------------------------------------------------

class TestMissingApiKey(unittest.TestCase):
    """Tests für den Fehlerfall eines fehlenden OPENROUTER_API_KEY."""

    def test_missing_api_key_raises_value_error(self):
        """Kein API-Key (weder Parameter noch Env-Var) → ValueError beim Konstruktor."""
        clean_env = {k: v for k, v in os.environ.items() if k != "OPENROUTER_API_KEY"}
        with patch.dict(os.environ, clean_env, clear=True):
            with self.assertRaises(ValueError) as ctx:
                OpenRouterWorker(api_key=None)
            self.assertIn("OPENROUTER_API_KEY", str(ctx.exception))

    def test_empty_api_key_raises_value_error(self):
        """Leerer String als API-Key → ValueError."""
        clean_env = {k: v for k, v in os.environ.items() if k != "OPENROUTER_API_KEY"}
        with patch.dict(os.environ, clean_env, clear=True):
            with self.assertRaises(ValueError):
                OpenRouterWorker(api_key="")


if __name__ == "__main__":
    unittest.main()
