import unittest
from soorin.contracts.grounded_context import GroundedClaim, validate_claims, extractive_answer
from soorin.contracts.triage_decision import TriageDecision, VERDICTS


class GroundedContextTests(unittest.TestCase):
    def test_all_five_verdicts_remain_distinct_reviewed_decisions(self):
        for verdict in VERDICTS:
            row=TriageDecision("D", "t", "A", "run", "auto-triage", verdict, 0.7,
                "uncalibrated agent self-report; not vendor risk", ("e",), "2026-11-05T00:00:00Z", "model@revision")
            self.assertEqual(row.to_dict()["verdict"], verdict)
            self.assertEqual(row.review_status, "pending")

    def test_missing_evidence_and_unknown_claims_are_rejected(self):
        context = {"schema_version": "soorin.knowledge-context.v2", "facts": [{"id": "f1", "predicate_label":"observed on", "object_value":None, "other_name":"synthetic host"}], "evidence_references": []}
        with self.assertRaises(ValueError):
            validate_claims(context, [GroundedClaim("x", ("f1",))])
        context["evidence_references"] = [{"fact_id": "f1", "source":{"chunk_id":"c1","document_id":"d1","doc_version":1}}]
        validate_claims(context, [GroundedClaim("observed on: synthetic host", ("f1",))])
        with self.assertRaises(ValueError):
            validate_claims(context, [GroundedClaim("the host is malicious", ("f1",))])
        self.assertEqual(extractive_answer(context)["claims"][0]["object"],"synthetic host")
        self.assertFalse(extractive_answer(context)["generated"])
        context["facts"][0]["contested"] = {"kind": "conflict"}
        with self.assertRaises(ValueError):
            validate_claims(context, [GroundedClaim("x", ("f1",))])
