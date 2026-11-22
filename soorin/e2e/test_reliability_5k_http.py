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


if __name__ == '__main__':
    unittest.main()
