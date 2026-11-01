from __future__ import annotations

import unittest

from soorin.identity import IdentityInput, canonical_key, normalize_hostname, normalize_ip, normalize_principal, resolve_identity
from soorin.identity.normalization import IdentityNormalizationError


class IdentityTests(unittest.TestCase):
    def test_same_host_id_across_alerts(self):
        args = dict(tenant_id="Tenant-A", source_system="cmdb", source_instance="prod", entity_type="Host", authoritative_id="ASSET-7")
        self.assertEqual(canonical_key(**args), canonical_key(**args))

    def test_same_hostname_in_two_tenants_never_merges(self):
        a = resolve_identity(IdentityInput("tenant-a", "splunk", "one", "Host", "DC01.EXAMPLE"))
        b = resolve_identity(IdentityInput("tenant-b", "splunk", "one", "Host", "dc01.example"))
        self.assertNotEqual(a.canonical_key, b.canonical_key)
        self.assertFalse(a.automatic)

    def test_private_ip_requires_network_scope(self):
        ambiguous = resolve_identity(IdentityInput("tenant-a", "splunk", "one", "IPAddress", "10.0.0.1"))
        scoped_a = resolve_identity(IdentityInput("tenant-a", "splunk", "one", "IPAddress", "10.0.0.1", scope="vpc-a"))
        scoped_b = resolve_identity(IdentityInput("tenant-a", "splunk", "one", "IPAddress", "10.0.0.1", scope="vpc-b"))
        self.assertEqual(ambiguous.status, "ambiguous")
        self.assertNotEqual(scoped_a.canonical_key, scoped_b.canonical_key)

    def test_host_rename_keeps_authoritative_key(self):
        old = resolve_identity(IdentityInput("t", "cmdb", "prod", "Host", "old.example", "asset-1"))
        new = resolve_identity(IdentityInput("t", "cmdb", "prod", "Host", "new.example", "asset-1"))
        self.assertEqual(old.canonical_key, new.canonical_key)
        self.assertNotEqual(old.normalized_value, new.normalized_value)

    def test_case_hostname_ip_and_principals_normalize(self):
        self.assertEqual(normalize_hostname(" DC01.Example. "), "dc01.example")
        self.assertEqual(normalize_ip("2001:0db8::1"), "2001:db8::1")
        self.assertEqual(normalize_principal("DOMAIN\\User.Name"), "domain\\user.name")
        self.assertEqual(normalize_principal("User@EXAMPLE.COM"), "user@example.com")

    def test_conflicting_authorities_and_malformed_identifiers(self):
        one = resolve_identity(IdentityInput("t", "splunk", "a", "SecurityAlert", "A-1", "A-1"))
        two = resolve_identity(IdentityInput("t", "splunk", "a", "SecurityAlert", "A-1", "A-2"))
        self.assertNotEqual(one.canonical_key, two.canonical_key)
        with self.assertRaises(IdentityNormalizationError):
            normalize_ip("999.1.1.1")
        with self.assertRaises(IdentityNormalizationError):
            normalize_hostname("bad host/name")

    def test_alias_candidates_require_review(self):
        known = resolve_identity(IdentityInput("t", "cmdb", "prod", "Host", "dc01", "asset-1"))
        proposed = resolve_identity(IdentityInput("t", "splunk", "prod", "Host", "DC01"), known_aliases=[known])
        self.assertEqual(proposed.status, "ambiguous")
        self.assertEqual(proposed.candidate_keys, (known.canonical_key,))


if __name__ == "__main__":
    unittest.main()
