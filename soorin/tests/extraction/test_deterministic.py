from __future__ import annotations

import unittest

from soorin.extraction import extract_entities


class ExtractionTests(unittest.TestCase):
    def test_structured_field_variants_and_windows_identity(self):
        batch = extract_entities({
            "src_ip": "192.0.2.7", "destination_ip": "2001:db8::8", "Computer": "DC01.EXAMPLE",
            "AccountName": "LAB\\Alice", "sha256": "a" * 64, "mitre_techniques": ["T1110.003"],
        }, source_record_reference="r1")
        pairs = {(row.entity_type, row.normalized_value) for row in batch.entities}
        self.assertIn(("IPAddress", "192.0.2.7"), pairs)
        self.assertIn(("IPAddress", "2001:db8::8"), pairs)
        self.assertIn(("Host", "dc01.example"), pairs)
        self.assertIn(("UserAccount", "lab\\alice"), pairs)
        self.assertIn(("MITRETechnique", "T1110.003"), pairs)

    def test_regex_does_not_scan_spl_or_macros(self):
        batch = extract_entities({
            "rule": {"spl": "search src=10.0.0.1 user=LAB\\admin", "macro_definitions": "allow 192.0.2.1"},
            "description": "Observed 203.0.113.9 and LAB\\analyst in multilingual گزارش امنیتی",
        }, source_record_reference="r2")
        values = {row.normalized_value for row in batch.entities}
        self.assertIn("203.0.113.9", values)
        self.assertIn("lab\\analyst", values)
        self.assertNotIn("10.0.0.1", values)
        self.assertNotIn("192.0.2.1", values)

    def test_structured_field_wins_over_regex_duplicate(self):
        batch = extract_entities({"src_ip": "192.0.2.1", "description": "Source 192.0.2.1"}, source_record_reference="r3")
        rows = [row for row in batch.entities if row.normalized_value == "192.0.2.1"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].extraction_method, "structured_field")

    def test_malformed_values_are_explicit_errors(self):
        batch = extract_entities({"src_ip": "999.2.3.4", "hostname": "bad host/name"}, source_record_reference="r4")
        self.assertEqual(batch.entities, ())
        self.assertEqual(len(batch.errors), 2)

    def test_paths_urls_tickets_and_hashes(self):
        text = "Process C:\\Windows\\System32\\cmd.exe opened https://synthetic.example/a for CHG-4242 hash " + "b" * 32
        batch = extract_entities({"description": text}, source_record_reference="r5")
        values = {row.normalized_value for row in batch.entities}
        self.assertIn("https://synthetic.example/a", values)
        self.assertIn("chg-4242", values)
        self.assertIn("b" * 32, values)


if __name__ == "__main__":
    unittest.main()
