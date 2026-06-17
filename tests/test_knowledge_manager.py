#!/usr/bin/env python3
"""test_knowledge_manager.py — Tests fuer das Knowledge-Manager-Script."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from knowledge_manager import (  # noqa: E402
    ArchiveCandidate,
    ReviewQueueEntry,
    ScanReport,
    _days_old,
    _find_knowledge_files,
    _count_references,
    _load_review_queue,
    _save_review_queue,
    _next_queue_id,
    _parse_yamlish,
    _repo_relative,
    find_archive_candidates,
    find_promote_candidates,
    find_delete_candidates,
    execute_archive,
    run_scan,
    parse_args,
)


class YamlishParserTests(unittest.TestCase):
    def test_parse_empty(self):
        result = _parse_yamlish("")
        self.assertEqual(result, {})

    def test_parse_comments_only(self):
        result = _parse_yamlish("# only a comment\n  # indented comment\n")
        self.assertEqual(result, {})

    def test_parse_simple_key_value(self):
        text = "key: value\nnum: 42\nflag: true\nnullval: null\n"
        result = _parse_yamlish(text)
        self.assertEqual(result.get("key"), "value")
        self.assertEqual(result.get("num"), 42)
        self.assertEqual(result.get("flag"), True)
        self.assertIsNone(result.get("nullval"))

    def test_parse_nested_block(self):
        text = "parent:\n  child: hello\n  num: 7\n"
        result = _parse_yamlish(text)
        self.assertIn("parent", result)
        self.assertEqual(result["parent"]["child"], "hello")
        self.assertEqual(result["parent"]["num"], 7)

    def test_parse_list(self):
        text = "items:\n  - one\n  - two\n  - 3\n"
        result = _parse_yamlish(text)
        self.assertIn("items", result)
        self.assertEqual(result["items"], ["one", "two", 3])

    def test_parse_nested_list_with_keys(self):
        text = (
            "conditions:\n"
            "  - name: test_rule\n"
            "    enabled: true\n"
            "  - name: second\n"
            "    days: 90\n"
        )
        result = _parse_yamlish(text)
        self.assertIn("conditions", result)
        self.assertEqual(len(result["conditions"]), 2)
        self.assertEqual(result["conditions"][0]["name"], "test_rule")
        self.assertEqual(result["conditions"][0]["enabled"], True)
        self.assertEqual(result["conditions"][1]["days"], 90)

    def test_parse_realistic_rules_subset(self):
        text = (
            "archive:\n"
            "  enabled: true\n"
            "  conditions:\n"
            "    - name: mtime_older_than\n"
            "      days: 90\n"
            "      paths:\n"
            "        - docs/BACKLOG/\n"
            "  excluded_paths:\n"
            "    - docs/AGENTS.md\n"
        )
        result = _parse_yamlish(text)
        archive = result.get("archive", {})
        self.assertTrue(archive["enabled"])
        self.assertEqual(len(archive["conditions"]), 1)
        self.assertEqual(archive["conditions"][0]["name"], "mtime_older_than")


class DaysOldTests(unittest.TestCase):
    def test_existing_file_returns_finite(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            tmp = Path(f.name)
        try:
            days = _days_old(tmp)
            self.assertGreater(days, 0)
            self.assertLess(days, 36500)
        finally:
            tmp.unlink()

    def test_nonexistent_file_returns_inf(self):
        days = _days_old(Path("/nonexistent/path/file.md"))
        self.assertEqual(days, float("inf"))


class FindKnowledgeFilesTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_empty_directory_returns_empty(self):
        files = _find_knowledge_files(
            directories=[str(self.tmp_path)]
        )
        self.assertEqual(files, [])

    def test_finds_md_files(self):
        sub = self.tmp_path / "docs"
        sub.mkdir(parents=True)
        (sub / "test.md").write_text("hello", encoding="utf-8")
        (sub / "notes.txt").write_text("hello", encoding="utf-8")
        files = _find_knowledge_files(
            directories=[str(self.tmp_path)],
            patterns=("*.md",),
        )
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].name, "test.md")


class CountReferencesTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.base = Path(self.tmpdir.name)
        import knowledge_manager as km
        self.orig_root = km.ROOT
        km.ROOT = self.base

    def tearDown(self):
        import knowledge_manager as km
        km.ROOT = self.orig_root
        self.tmpdir.cleanup()

    def test_no_references(self):
        a = self.base / "a.md"
        a.write_text("no match here", encoding="utf-8")
        count = _count_references("target", [a])
        self.assertEqual(count, 0)

    def test_one_reference(self):
        a = self.base / "a.md"
        a.write_text("this references target_stem here", encoding="utf-8")
        count = _count_references("target_stem", [a])
        self.assertEqual(count, 1)

    def test_exclude_archive_path(self):
        archived = self.base / "docs" / "archive" / "old.md"
        archived.parent.mkdir(parents=True)
        archived.write_text("references target_stem", encoding="utf-8")
        all_files = [archived]
        # Patch ROOT so _repo_relative works for temp dir
        count = _count_references("target_stem", all_files)
        self.assertEqual(count, 0)


class ReviewQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.queue_path = Path(self.tmpdir.name) / "queue.json"

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_empty_queue_returns_empty_list(self):
        queue = _load_review_queue(self.queue_path)
        self.assertEqual(queue, [])

    def test_save_and_load(self):
        entries = [
            {"id": "queue-0001", "action": "promote", "target": "test.md",
             "status": "pending", "requested_at": "2026-01-01T00:00:00"}
        ]
        _save_review_queue(entries, self.queue_path)
        loaded = _load_review_queue(self.queue_path)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["id"], "queue-0001")

    def test_next_queue_id(self):
        queue = [
            {"id": "queue-0001"},
            {"id": "queue-0003"},
        ]
        # Finds first gap: queue-0002
        self.assertEqual(_next_queue_id(queue), "queue-0002")

    def test_next_queue_id_from_empty(self):
        self.assertEqual(_next_queue_id([]), "queue-0001")


class FindArchiveCandidatesTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.base = Path(self.tmpdir.name)
        self.docs = self.base / "docs"
        self.docs.mkdir(parents=True)
        self.archive = self.base / "docs" / "archive"
        self.archive.mkdir(parents=True)
        import knowledge_manager as km
        self.orig_root = km.ROOT
        km.ROOT = self.base

    def tearDown(self):
        import knowledge_manager as km
        km.ROOT = self.orig_root
        self.tmpdir.cleanup()

    def _make_rules_cfg(self, enabled: bool = True, days: int = 90):
        return {
            "archive": {
                "enabled": enabled,
                "conditions": [
                    {
                        "name": "mtime_older_than",
                        "enabled": True,
                        "days": days,
                        "paths": ["docs/"],
                    }
                ],
                "excluded_paths": [],
            }
        }

    def test_no_candidates_when_all_files_recent(self):
        (self.docs / "recent.md").write_text("current", encoding="utf-8")
        files = [self.docs / "recent.md"]
        rules = self._make_rules_cfg()
        candidates = find_archive_candidates(files, rules, files)
        self.assertEqual(len(candidates), 0)

    def test_old_file_is_candidate(self):
        old = self.docs / "old.md"
        old.write_text("old content", encoding="utf-8")
        past = datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp()
        os.utime(old, (past, past))

        files = [old]
        rules = self._make_rules_cfg(days=30)
        candidates = find_archive_candidates(files, rules, files)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].rule_name, "mtime_older_than")

    def test_already_archived_file_not_candidate(self):
        old = self.archive / "already.md"
        old.write_text("archived", encoding="utf-8")
        past = datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp()
        os.utime(old, (past, past))

        files = [old]
        rules = self._make_rules_cfg(days=30)
        candidates = find_archive_candidates(files, rules, files)
        self.assertEqual(len(candidates), 0)

    def test_excluded_path_not_candidate(self):
        important = self.docs / "AGENTS.md"
        important.write_text("important", encoding="utf-8")
        past = datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp()
        os.utime(important, (past, past))

        files = [important]
        rules = {
            "archive": {
                "enabled": True,
                "conditions": [
                    {
                        "name": "mtime_older_than",
                        "enabled": True,
                        "days": 30,
                        "paths": ["docs/"],
                    }
                ],
                "excluded_paths": ["docs/AGENTS.md"],
            }
        }
        candidates = find_archive_candidates(files, rules, files)
        self.assertEqual(len(candidates), 0)


class FindPromoteCandidatesTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.base = Path(self.tmpdir.name)
        import knowledge_manager as km
        self.orig_root = km.ROOT
        km.ROOT = self.base

    def tearDown(self):
        import knowledge_manager as km
        km.ROOT = self.orig_root
        self.tmpdir.cleanup()

    def test_no_candidates_when_no_frequent_refs(self):
        a = self.base / "a.md"
        a.write_text("content", encoding="utf-8")
        rules = {
            "promote": {
                "enabled": True,
                "conditions": [
                    {
                        "name": "frequently_referenced",
                        "enabled": True,
                        "min_reference_count": 3,
                    }
                ],
            }
        }
        candidates = find_promote_candidates([a], rules, [a], [])
        self.assertEqual(len(candidates), 0)

    def test_frequently_referenced_is_candidate(self):
        target = self.base / "target.md"
        target.write_text("content", encoding="utf-8")

        # Create 3 files that reference "target"
        for i in range(3):
            ref = self.base / f"ref{i}.md"
            ref.write_text("references target here", encoding="utf-8")

        all_files = [target] + [self.base / f"ref{i}.md" for i in range(3)]
        rules = {
            "promote": {
                "enabled": True,
                "conditions": [
                    {
                        "name": "frequently_referenced",
                        "enabled": True,
                        "min_reference_count": 3,
                    }
                ],
            }
        }
        candidates = find_promote_candidates(all_files, rules, all_files, [])
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].action, "promote")

    def test_already_queued_not_duplicated(self):
        target = self.base / "target.md"
        target.write_text("content", encoding="utf-8")
        for i in range(3):
            (self.base / f"ref{i}.md").write_text(
                "references target", encoding="utf-8"
            )

        all_files = [target] + [self.base / f"ref{i}.md" for i in range(3)]
        rules = {
            "promote": {
                "enabled": True,
                "conditions": [
                    {
                        "name": "frequently_referenced",
                        "enabled": True,
                        "min_reference_count": 3,
                    }
                ],
            }
        }
        existing = [{"target": "target.md"}]
        candidates = find_promote_candidates(all_files, rules, all_files, existing)
        self.assertEqual(len(candidates), 0)

    def test_manual_tag_detected(self):
        tagged = self.base / "tagged.md"
        tagged.write_text("promote-candidate\nsome content\n", encoding="utf-8")
        rules = {
            "promote": {
                "enabled": True,
                "conditions": [
                    {
                        "name": "manual_tag",
                        "enabled": True,
                        "marker": "promote-candidate",
                    }
                ],
            }
        }
        candidates = find_promote_candidates([tagged], rules, [tagged], [])
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].action, "promote")
        self.assertIn("promote-candidate", candidates[0].reason)


class FindDeleteCandidatesTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.base = Path(self.tmpdir.name)
        self.archive = self.base / "docs" / "archive"
        self.archive.mkdir(parents=True)
        import knowledge_manager as km
        self.orig_root = km.ROOT
        km.ROOT = self.base

    def tearDown(self):
        import knowledge_manager as km
        km.ROOT = self.orig_root
        self.tmpdir.cleanup()

    def _make_rules(self, archived_days: int = 365, orphan_days: int = 180):
        return {
            "delete": {
                "enabled": True,
                "conditions": [
                    {
                        "name": "archived_longer_than",
                        "enabled": True,
                        "days": archived_days,
                    },
                    {
                        "name": "orphaned_long_term",
                        "enabled": True,
                        "days": orphan_days,
                    },
                ],
                "excluded_paths": ["docs/AGENTS.md", "README.md", "LICENSE"],
            }
        }

    def test_no_candidates_when_all_recent(self):
        recent = self.archive / "recent.md"
        recent.write_text("recent", encoding="utf-8")
        candidates = find_delete_candidates(
            [recent], self._make_rules(), [recent], []
        )
        self.assertEqual(len(candidates), 0)

    def test_old_archived_file_is_candidate(self):
        old = self.archive / "old.md"
        old.write_text("old", encoding="utf-8")
        past = datetime(2018, 1, 1, tzinfo=timezone.utc).timestamp()
        os.utime(old, (past, past))

        candidates = find_delete_candidates(
            [old], self._make_rules(archived_days=30), [old], []
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].action, "delete")
        self.assertEqual(candidates[0].rule_name, "archived_longer_than")

    def test_excluded_file_not_queued(self):
        protected = self.base / "README.md"
        protected.write_text("readme", encoding="utf-8")
        past = datetime(2010, 1, 1, tzinfo=timezone.utc).timestamp()
        os.utime(protected, (past, past))

        candidates = find_delete_candidates(
            [protected], self._make_rules(orphan_days=1), [protected], []
        )
        self.assertEqual(len(candidates), 0)


class ExecuteArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.base = Path(self.tmpdir.name)
        self.source_dir = self.base / "docs"
        self.source_dir.mkdir(parents=True)
        self.archive_dir = self.base / "doc_archive"

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_archive_moves_file(self):
        src = self.source_dir / "test.md"
        src.write_text("content", encoding="utf-8")

        # We use ROOT-based path, so we patch ROOT temporarily
        import knowledge_manager as km
        original_root = km.ROOT
        try:
            km.ROOT = self.base
            km.ARCHIVE_DIR = self.archive_dir

            cand = ArchiveCandidate(
                file_path=src,
                rule_name="mtime_older_than",
                mtime_days_ago=100,
                reference_count=0,
                reason="too old",
            )
            count = execute_archive([cand])
            self.assertEqual(count, 1)
            # File should now be in archive
            expected = self.archive_dir / "docs" / "test.md"
            self.assertTrue(expected.exists())
            self.assertFalse(src.exists())
        finally:
            km.ROOT = original_root


class RunScanIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.base = Path(self.tmpdir.name)
        # Create a minimal rules file
        self.rules_path = self.base / "rules.yaml"
        self.rules_path.write_text(
            "archive:\n"
            "  enabled: true\n"
            "  conditions:\n"
            "    - name: mtime_older_than\n"
            "      enabled: true\n"
            "      days: 365000  # very high, won't trigger\n"
            "      paths:\n"
            "        - docs/\n"
            "  excluded_paths: []\n"
            "promote:\n"
            "  enabled: true\n"
            "  require_human_approval: true\n"
            "  conditions:\n"
            "    - name: frequently_referenced\n"
            "      enabled: true\n"
            "      min_reference_count: 10\n"
            "delete:\n"
            "  enabled: true\n"
            "  require_human_approval: true\n"
            "  conditions:\n"
            "    - name: orphaned_long_term\n"
            "      enabled: true\n"
            "      days: 365000\n"
            "  excluded_paths: []\n"
            "human_review_queue:\n"
            "  path: queue.json\n"
            "  format: json\n"
            "paths:\n"
            "  knowledge_directories:\n"
            "    - docs/\n"
            "  archive_directory: docs/archive/\n",
            encoding="utf-8",
        )
        self.queue_path = self.base / "queue.json"

        import knowledge_manager as km
        self._original_root = km.ROOT
        km.ROOT = self.base
        km.KNOWLEDGE_DIRECTORIES = ["docs/"]
        km.ARCHIVE_DIR = self.base / "docs" / "archive"

        # Create a recent doc
        self.docs = self.base / "docs"
        self.docs.mkdir(exist_ok=True)
        (self.docs / "readme.md").write_text("hello", encoding="utf-8")

    def tearDown(self):
        import knowledge_manager as km
        km.ROOT = self._original_root
        km.KNOWLEDGE_DIRECTORIES = ["docs/", ".agents/skills/", ".skills/"]
        km.ARCHIVE_DIR = Path(__file__).resolve().parents[1] / "docs" / "archive"
        self.tmpdir.cleanup()

    def test_scan_runs_without_errors(self):
        import knowledge_manager as km
        report = km.run_scan(
            rules_path=self.rules_path,
            queue_path=self.queue_path,
        )
        self.assertIsInstance(report, ScanReport)
        self.assertGreaterEqual(report.total_files, 0)
        self.assertIn("scanned_at", str(vars(report)))


class ParseArgsTests(unittest.TestCase):
    def test_scan_command(self):
        args = parse_args(["scan"])
        self.assertEqual(args.command, "scan")

    def test_queue_command(self):
        args = parse_args(["queue"])
        self.assertEqual(args.command, "queue")

    def test_archive_command(self):
        args = parse_args(["archive"])
        self.assertEqual(args.command, "archive")

    def test_archive_with_dry_run(self):
        args = parse_args(["archive", "--dry-run"])
        self.assertTrue(args.dry_run)

    def test_status_command(self):
        args = parse_args(["status"])
        self.assertEqual(args.command, "status")

    def test_queue_with_status_filter(self):
        args = parse_args(["queue", "--status", "approved"])
        self.assertEqual(args.status, "approved")


class RepoRelativeTests(unittest.TestCase):
    def test_repo_relative_returns_stem(self):
        import knowledge_manager as km
        known = km.ROOT / "docs" / "test.md"
        rel = _repo_relative(known)
        self.assertEqual(rel, "docs/test.md")


if __name__ == "__main__":
    unittest.main()
