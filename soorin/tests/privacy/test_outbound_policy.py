from __future__ import annotations
import unittest
from soorin.privacy.outbound import OutboundDataPolicy, OutboundPolicyError

class OutboundPolicyTests(unittest.TestCase):
    def test_claimed_gateway_route_does_not_bypass_sensitive_policy(self):
        policy = OutboundDataPolicy("block_sensitive")
        decision = policy.evaluate(["SOC alert on 192.0.2.45"], purpose="embedding", approved_privacy_route=True)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "sensitive_content_requires_verified_privacy_route")
        with self.assertRaises(OutboundPolicyError):
            policy.require_allowed(["SOC alert"], purpose="embedding", approved_privacy_route=True)

    def test_block_all_overrides_all_flags(self):
        policy = OutboundDataPolicy("block_all")
        self.assertFalse(policy.evaluate(["synthetic SOC alert"], purpose="embedding", synthetic=True, approved_privacy_route=True).allowed)

    def test_synthetic_opt_in_and_regular_nonsensitive(self):
        policy = OutboundDataPolicy("block_sensitive")
        self.assertTrue(policy.evaluate(["synthetic malware example"], purpose="embedding", synthetic=True).allowed)
        self.assertTrue(policy.evaluate(["general example"], purpose="embedding").allowed)

if __name__ == "__main__":
    unittest.main()
