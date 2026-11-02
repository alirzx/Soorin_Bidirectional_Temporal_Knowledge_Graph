from __future__ import annotations

import argparse
import unittest

from soorin.e2e.local_validation import DEFAULT_FIXTURE, build_report, select_isolated_api


class E2EValidationTests(unittest.TestCase):
    def test_only_isolated_loopback_api_is_allowed(self):
        self.assertEqual(select_isolated_api("http://127.0.0.1:2516"), "http://127.0.0.1:2516")
        for url in (
            "http://127.0.0.1:1516", "http://localhost:9999", "http://example.test:2516",
            "https://127.0.0.1:2516", "http://user:secret@127.0.0.1:2516",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                select_isolated_api(url)

    def test_offline_report_is_machine_readable_and_truthful(self):
        args = argparse.Namespace(
            fixture=DEFAULT_FIXTURE,
            base_url="http://127.0.0.1:2516",
            execute=False,
            semantic_enabled=False,
            timeout=1.0,
            poll_seconds=0.0,
            report=None,
        )
        report, exit_code = build_report(args)
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["schema_version"], "soorin.soc.e2e-report.v1")
        self.assertTrue(report["synthetic"])
        statuses = {item["name"]: item["status"] for item in report["checks"]}
        self.assertEqual(statuses["normalize_and_render"], "PASS")
        self.assertEqual(statuses["required_entity_coverage"], "PASS")
        self.assertEqual(statuses["statements_push"], "NOT RUN")
        self.assertEqual(statuses["persistent_identity_conflict"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
