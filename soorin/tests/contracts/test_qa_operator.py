"""Offline regression tests for QA login and deterministic Splunk fixture."""
from __future__ import annotations
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib import error

from soorin.ops import qa_login, qa_existing_kb
from soorin.tests.mock_splunk.scripts.curated_qa_dataset import generate, make_record


class QaOperatorTests(unittest.TestCase):
    def test_login_uses_no_tty_capture_and_restricts_base(self):
        with self.assertRaises(ValueError):
            qa_login.authenticate("http://example.invalid", "qa@example.invalid", "x")
        with patch("sys.stdin.isatty", return_value=False):
            with self.assertRaises(SystemExit) as raised:
                qa_login.main([])
        self.assertNotEqual(raised.exception.code, 0)

    def test_private_session_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.json"
            qa_login.save_token(path, "dummy-qa-token")
            self.assertEqual(path.stat().st_mode & 0o077, 0)
            self.assertEqual(qa_login.load_token(path), "dummy-qa-token")
            with patch.dict(os.environ, {"UTOPIA_SESSION_TOKEN": ""}):
                with patch.object(qa_login, "load_token", return_value=qa_login.load_token(path)):
                    self.assertEqual(qa_existing_kb.session_token(), "dummy-qa-token")
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                qa_login.load_token(path)

    def test_existing_kb_only_does_not_create(self):
        with patch.object(qa_existing_kb, "api", side_effect=[
            [{"id": "ws-a", "name": "Existing Workspace"}],
            [{"id": "kb-b", "name": "Soorin SOC Synthetic Lab"}]
        ]):
            workspace, kb = qa_existing_kb.find_existing_kb("dummy", "Soorin SOC Synthetic Lab")
            self.assertEqual(workspace["id"], "ws-a")
            self.assertEqual(kb["id"], "kb-b")

    def test_partial_receipt_coverage_must_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "receipts.jsonl"
            path.write_text(json.dumps({"kb_id": "kb", "dataset": "alerts.jsonl",
                                        "index": 0, "receipt_id": "id"}) + "\n")
            with patch.object(qa_existing_kb, "state_file", return_value=path):
                with self.assertRaises(SystemExit):
                    qa_existing_kb.tracked_receipts("kb", "alerts.jsonl", 0, 10)

    def test_fixture_stable_and_distinct_revision(self):
        first = make_record(0)
        self.assertEqual(first["alert_row_id"], "soc-alert-synthetic-00000")
        self.assertEqual(first["llm_payload"]["_meta"]["mode"], "enriched_from_api")
        second = make_record(0, revision=2)
        self.assertEqual(first["alert_row_id"], second["alert_row_id"])
        self.assertNotEqual(first["source_revision_id"], second["source_revision_id"])
        self.assertNotEqual(first["source_updated_at"], second["source_updated_at"])

    def test_dataset_generation_counts_and_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "fixtures"
            manifest = generate(root, 12, 2)
            self.assertEqual(manifest["alerts"], 12)
            self.assertEqual(manifest["separate_revisions"], 2)
            self.assertEqual(len((root / "alerts.jsonl").read_text().splitlines()), 12)
            self.assertEqual(len((root / "revisions.jsonl").read_text().splitlines()), 2)
            with self.assertRaises(FileExistsError):
                generate(root, 12, 2)


if __name__ == "__main__":
    unittest.main()
