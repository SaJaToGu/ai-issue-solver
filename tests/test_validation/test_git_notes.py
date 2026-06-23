from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from validation.git_notes import (  # noqa: E402
    NOTES_REF,
    add_sub_issues_to_note,
    ensure_notes_ref,
    get_sub_issues_for_pr,
    read_note,
    write_note,
)


def _init_temp_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=path, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=path, capture_output=True, check=True,
    )
    readme = path / "README.md"
    readme.write_text("# test", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=path, capture_output=True, check=True,
    )


class GitNotesTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        _init_temp_repo(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_ensure_notes_ref_creates_note(self):
        ensure_notes_ref(repo_root=self.tmpdir)
        note = read_note(repo_root=self.tmpdir)
        self.assertEqual(note, {})

    def test_write_and_read_note(self):
        ensure_notes_ref(repo_root=self.tmpdir)
        data = {"42": [{"number": 100, "title": "sub-issue"}]}
        write_note(data, repo_root=self.tmpdir)
        note = read_note(repo_root=self.tmpdir)
        self.assertEqual(note, data)

    def test_read_note_when_no_note_exists(self):
        note = read_note(repo_root=self.tmpdir)
        self.assertEqual(note, {})

    def test_add_sub_issues_to_note(self):
        ensure_notes_ref(repo_root=self.tmpdir)
        sub = [{"number": 100, "title": "sub-1", "url": "http://example.com/100"}]
        add_sub_issues_to_note(42, sub, repo_root=self.tmpdir)
        subs = get_sub_issues_for_pr(42, repo_root=self.tmpdir)
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["number"], 100)

    def test_get_sub_issues_for_pr_nonexistent(self):
        ensure_notes_ref(repo_root=self.tmpdir)
        subs = get_sub_issues_for_pr(999, repo_root=self.tmpdir)
        self.assertEqual(subs, [])

    def test_add_multiple_sub_issues_to_same_parent(self):
        ensure_notes_ref(repo_root=self.tmpdir)
        add_sub_issues_to_note(42, [{"number": 100}], repo_root=self.tmpdir)
        add_sub_issues_to_note(42, [{"number": 101}], repo_root=self.tmpdir)
        subs = get_sub_issues_for_pr(42, repo_root=self.tmpdir)
        self.assertEqual(len(subs), 2)

    def test_write_note_empty_dict(self):
        ensure_notes_ref(repo_root=self.tmpdir)
        write_note({}, repo_root=self.tmpdir)
        note = read_note(repo_root=self.tmpdir)
        self.assertEqual(note, {})

    def test_read_note_after_git_note_add_external(self):
        ensure_notes_ref(repo_root=self.tmpdir)
        payload = json.dumps({"99": [{"number": 200}]})
        subprocess.run(
            ["git", "notes", "--ref", NOTES_REF, "add", "-f", "-m", payload, "HEAD"],
            cwd=self.tmpdir, capture_output=True, check=True,
        )
        note = read_note(repo_root=self.tmpdir)
        self.assertIn("99", note)


if __name__ == "__main__":
    unittest.main()
