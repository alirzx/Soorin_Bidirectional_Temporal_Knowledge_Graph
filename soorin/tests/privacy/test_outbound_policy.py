from __future__ import annotations
import unittest
from soorin.privacy.outbound import OutboundDataPolicy, OutboundPolicyError

class OutboundPolicyTests(unittest.TestCase):
    def test_sensitive_external_content_requires_injected_verifier(self):
        policy = OutboundDataPolicy("block_sensitive")
        decision = policy.evaluate(["SOC alert on 192.0.2.45"], purpose="embedding")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "sensitive_content_requires_verified_privacy_route")
        with self.assertRaises(OutboundPolicyError):
            policy.require_allowed(["SOC alert"], purpose="embedding")

        verified = OutboundDataPolicy(
            "block_sensitive", route_verifier=lambda purpose, fingerprint: "gateway-attestation-1",
        ).evaluate(["SOC alert on 192.0.2.45"], purpose="embedding")
        self.assertTrue(verified.allowed)
        self.assertEqual(verified.reason, "verified_privacy_route")
        self.assertEqual(verified.route_attestation_id, "gateway-attestation-1")

    def test_block_all_overrides_all_flags(self):
        policy = OutboundDataPolicy("block_all")
        self.assertFalse(policy.evaluate(["synthetic SOC alert"], purpose="embedding", synthetic=True).allowed)

    def test_synthetic_requires_policy_test_mode(self):
        policy = OutboundDataPolicy("block_sensitive")
        decision = policy.evaluate(["synthetic malware example"], purpose="embedding", synthetic=True)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "synthetic_requires_test_mode")
        test_policy = OutboundDataPolicy("block_sensitive", test_mode=True)
        self.assertTrue(test_policy.evaluate(["synthetic malware example"], purpose="embedding", synthetic=True).allowed)
        self.assertTrue(policy.evaluate(["general example"], purpose="embedding").allowed)

    def test_local_trust_is_deployment_policy_not_a_request_flag(self):
        policy = OutboundDataPolicy("block_sensitive", endpoint_trust="local_trusted")
        decision = policy.evaluate(["SOC alert on 192.0.2.45"], purpose="reranker")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "local_trusted_endpoint")

    def test_verifier_failure_is_closed_and_audit_contains_no_content(self):
        audited = []
        policy = OutboundDataPolicy(
            route_verifier=lambda purpose, fingerprint: (_ for _ in ()).throw(RuntimeError("fail")),
            audit_sink=audited.append,
        )
        decision = policy.evaluate(["SOC alert secret@example.test"], purpose="chat")
        self.assertFalse(decision.allowed)
        self.assertEqual(len(decision.content_fingerprint), 64)
        self.assertNotIn("secret@example.test", repr(audited))

if __name__ == "__main__":
    unittest.main()
