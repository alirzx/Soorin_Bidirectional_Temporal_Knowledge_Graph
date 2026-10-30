"""No-network contract tests for the rc9 synthetic SOC lab."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import soc_mock


class SyntheticSocContractTests(unittest.TestCase):
    def setUp(self):
        self.records = soc_mock.load_records()

    def test_nine_records_cover_splunk_and_soc(self):
        self.assertEqual(len(self.records), 9)
        self.assertEqual({x["kind"] for x in self.records}, {"notable", "alert", "event", "case", "jira"})

    def test_all_payloads_match_open_contract(self):
        for row in self.records:
            payload = soc_mock.to_statements(row)
            soc_mock.validate_contract(payload)
            self.assertEqual(row["id"], payload["external_id"])
            self.assertEqual(row["_time"], payload["doc_time"])

    def test_notable_has_detection_host_ip_and_case_edges(self):
        p = soc_mock.to_statements(self.records[0])
        links = {(s[2], s[3]) for s in p["s"] if s[3] is not None}
        self.assertIn(("observed on host", "dc-auth-01.corp.example"), links)
        self.assertIn(("observed source ip", "192.0.2.44"), links)
        self.assertIn(("mapped to technique", "T1110.003"), links)
        self.assertIn(("linked to case", "SOC-CASE-001"), links)

    def test_splunk_field_aliases(self):
        event = next(x for x in self.records if x["id"] == "SPLUNK-EVENT-4625-002")
        p = soc_mock.to_statements(event)
        link_targets = [s[3] for s in p["s"] if s[3] is not None]
        for value in ("dc-auth-01.corp.example", "192.0.2.44", "lab-user-02"):
            self.assertIn(value, link_targets)

    def test_deterministic_replay_payload(self):
        left = soc_mock.to_statements(self.records[0])
        right = soc_mock.to_statements(self.records[0])
        self.assertEqual(json.dumps(left, sort_keys=True), json.dumps(right, sort_keys=True))

    def test_malformed_payload_refused_locally(self):
        payload = soc_mock.to_statements(self.records[0])
        payload["s"][0][0] = "not-null"
        with self.assertRaises(ValueError):
            soc_mock.validate_contract(payload)

    def test_non_synthetic_dataset_refused(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as tmp:
            filename = Path(tmp) / "fixture.json"
            filename.write_text(json.dumps({"synthetic": False, "records": self.records}))
            with self.assertRaises(ValueError):
                soc_mock.load_records(filename)


if __name__ == "__main__":
    unittest.main()
