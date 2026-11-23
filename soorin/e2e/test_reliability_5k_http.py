"""Offline unit checks for soorin/e2e/reliability_5k_http.py.
Run after copying: python3 -m unittest soorin.e2e.test_reliability_5k_http -v
"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from soorin.e2e import reliability_5k_http as m


class Reliability5KTests(unittest.TestCase):
    def test_summarizes_all_receipt_statuses(self):
        self.assertEqual(m.status_groups({"groups": [
            {"status": "bound", "count": 18}, {"status": "bound", "count": 2},
            {"status": "submitted", "count": 3}]}), {"bound": 20, "submitted": 3})
        with self.assertRaisesRegex(RuntimeError, "missing groups"):
            m.status_groups({"counts": []})

    def test_rejects_prod_and_shared_targets(self):
        for base in ("http://127.0.0.1:2516", "https://127.0.0.1:2626",
                     "http://192.168.0.55:2626", "http://localhost:2626"):
            with self.assertRaises(RuntimeError):
                m.verify_disposable_target(base, m.DEFAULT_PROJECT, 2627)

    def test_checks_target_container_ownership(self):
        def owned(project, service):
            suffix = 'data' if service == 'app' else 'db'
            port = '1516/tcp' if service == 'app' else '5432/tcp'
            published = '2626' if service == 'app' else '2627'
            return {
                'Config': {'Labels': {'com.docker.compose.project': m.DEFAULT_PROJECT,
                                      'com.docker.compose.service': service}},
                'State': {'Running': True},
                'NetworkSettings': {'Ports': {port: [{'HostIp': '127.0.0.1', 'HostPort': published}]}},
                'Mounts': [{'Destination': '/app/data' if service == 'app' else '/var/lib/postgresql/data',
                            'Type': 'volume', 'Name': f'{m.DEFAULT_PROJECT}_soorin_sprint1_{suffix}'}],
            }
        with patch.object(m, '_docker_inspect', side_effect=owned):
            m.verify_disposable_target(m.DEFAULT_BASE, m.DEFAULT_PROJECT, 2627)

    def test_acceptances_can_resume(self):
        with TemporaryDirectory() as tmp:
            p = Path(tmp) / 'accepted.jsonl'
            p.write_text(json.dumps({'item': 'alerts.jsonl:0', 'receipt_id': 'receipt-0'}) + '\n')
            self.assertEqual(m.existing_acceptances(p), {'alerts.jsonl:0': 'receipt-0'})

    def test_receipt_verification_requires_bound_and_evidence(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            data = b'{}\n'
            (out / 'alerts.jsonl').write_bytes(data)
            (out / 'manifest.json').write_text(json.dumps({'files_sha256': {
                'alerts.jsonl': m.hashlib.sha256(data).hexdigest()}}))
            (out / 'accepted.jsonl').write_text(json.dumps({
                'item': 'alerts.jsonl:0', 'receipt_id': '00000000-0000-0000-0000-000000000001'}) + '\n')
            def remote(url, token, **kwargs):
                if url.endswith('/summary'):
                    return {'groups': [{'status': 'bound', 'count': 1}]}
                return {'status': 'bound', 'document': {'status': 'ready', 'graph_status': 'done'},
                        'relations': [{'binding': {'evidence_link_status': True}}]}
            with patch.object(m, '_json', side_effect=remote):
                m.verify(out, m.DEFAULT_BASE, 'kb', 'synthetic-token', False, 1, .01, 1)
            result = json.loads((out / 'acceptance-report.json').read_text())
            self.assertTrue(result['receipt_binding_pass'])
            self.assertTrue(result['sampled_graph_pass'])


    def test_server_target_requires_exact_private_ports_and_volumes(self):
        project = "soorin-tkg-server55"
        app_volume = "soorin-tkg-server55_fresh_data_20261123"
        db_volume = "soorin-tkg-server55_fresh_db_20261123"
        def inspected(name, service):
            self.assertEqual(name, project)
            app = service == "app"
            return {
                "Config": {"Labels": {"com.docker.compose.project": name,
                                      "com.docker.compose.service": service}},
                "State": {"Running": True},
                "NetworkSettings": {"Ports": {
                    "1516/tcp" if app else "5432/tcp": [{
                        "HostIp": "192.168.0.55" if app else "127.0.0.1",
                        "HostPort": "2516" if app else "2517"}]}},
                "Mounts": [{"Type": "volume", "Destination":
                            "/app/data" if app else "/var/lib/postgresql/data",
                            "Name": app_volume if app else db_volume}],
            }
        with patch.object(m, "_docker_inspect", side_effect=inspected):
            m.verify_server_target("http://192.168.0.55:2516", project, 2517,
                                   app_volume, db_volume)
            with self.assertRaisesRegex(RuntimeError, "volume ownership mismatch"):
                m.verify_server_target("http://192.168.0.55:2516", project, 2517,
                                       "soorin-tkg-server55_wrong", db_volume)
            with self.assertRaisesRegex(RuntimeError, "port mapping mismatch"):
                m.verify_server_target("http://192.168.0.55:2518", project, 2517,
                                       app_volume, db_volume)
        for url in ("http://8.8.8.8:2516", "https://192.168.0.55:2516",
                    "http://example.com:2516"):
            with self.assertRaises(RuntimeError):
                m.verify_server_target(url, project, 2517, app_volume, db_volume)

    def test_server_receipt_verification_ignores_prior_kb_receipts(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            data = b'{}\\n'
            (out / "alerts.jsonl").write_bytes(data)
            (out / "manifest.json").write_text(json.dumps({"files_sha256": {
                "alerts.jsonl": m.hashlib.sha256(data).hexdigest()}}))
            (out / "accepted.jsonl").write_text(json.dumps({
                "item": "alerts.jsonl:0", "receipt_id": "receipt-new"}) + "\\n")
            def remote(url, token, **kwargs):
                if "/knowledge/receipts?limit=100" in url:
                    return {"receipts": [
                        {"receipt_id": "receipt-old", "status": "failed"},
                        {"receipt_id": "receipt-new", "status": "bound", "delivery_state": "bound"}],
                        "next_cursor": None}
                if url.endswith("/receipt-new"):
                    return {"status": "bound", "document": {
                        "status": "ready", "graph_status": "done"},
                        "relations": [{"binding": {"evidence_link_status": True}}]}
                raise AssertionError(url)
            with patch.object(m, "_json", side_effect=remote):
                m.verify(out, "http://192.168.0.55:2516", "kb",
                         "session", False, 1, .01, 1, run_scoped=True)
            report = json.loads((out / "acceptance-report.json").read_text())
            self.assertEqual(report["groups"], {"bound": 1})
            self.assertTrue(report["receipt_binding_pass"])

    def test_duplicate_receipt_ids_are_not_5500_distinct_admissions(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            blob = b'{}\\n{}\\n'
            (out / "alerts.jsonl").write_bytes(blob)
            (out / "manifest.json").write_text(json.dumps({"files_sha256": {
                "alerts.jsonl": m.hashlib.sha256(blob).hexdigest()}}))
            (out / "accepted.jsonl").write_text(
                json.dumps({"item": "alerts.jsonl:0", "receipt_id": "replayed"}) + "\\n" +
                json.dumps({"item": "alerts.jsonl:1", "receipt_id": "replayed"}) + "\\n")
            with self.assertRaisesRegex(RuntimeError, "same receipt"):
                m.verify(out, m.DEFAULT_BASE, "kb", "session", False, 1, .01, 1, run_scoped=True)

    def test_fixture_generation_start_index_avoids_smoke_record(self):
        with TemporaryDirectory() as tmp:
            from soorin.tests.mock_splunk.scripts.curated_qa_dataset import generate
            out = Path(tmp) / "test-fixtures"
            report = generate(out, 2, 1, start_index=1)
            alert = json.loads((out / "alerts.jsonl").read_text().splitlines()[0])
            revision = json.loads((out / "revisions.jsonl").read_text().splitlines()[0])
            self.assertEqual(report["start_index"], 1)
            self.assertEqual(alert["record"]["alert_row_id"], "soc-alert-synthetic-00001")
            self.assertEqual(revision["record"]["source_revision_id"], "rev-2-00001")

if __name__ == '__main__':
    unittest.main()
