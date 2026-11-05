import unittest
from soorin.identity import IdentityInput, resolve_identity

class ScopeRegressionTests(unittest.TestCase):
    def item(self, tenant='a', source='splunk', instance='one', authority=None, value='host-01'):
        return IdentityInput(tenant,source,instance,'Host',value,authority)

    def test_provisional_cross_source_collision_is_characterized_not_auto_resolution(self):
        a=resolve_identity(self.item())
        for item in [self.item(source='edr'),self.item(instance='two')]:
            b=resolve_identity(item,known_aliases=[a])
            self.assertEqual(a.canonical_key,b.canonical_key)  # Established v1 behavior.
            self.assertFalse(a.automatic)
            self.assertFalse(b.automatic)
            self.assertIn(b.status,{'provisional','ambiguous'})
        self.assertNotEqual(a.canonical_key,resolve_identity(self.item(tenant='b')).canonical_key)

    def test_authority_is_source_scoped_and_aliases_do_not_override_it(self):
        a=resolve_identity(self.item(authority='asset-a'))
        for item in [self.item(source='edr',authority='asset-a'),self.item(instance='two',authority='asset-a'),
                     self.item(authority='asset-b'),self.item(tenant='b',authority='asset-a')]:
            self.assertNotEqual(a.canonical_key,resolve_identity(item,known_aliases=[a]).canonical_key)
        renamed=resolve_identity(self.item(authority='asset-a',value='host-renamed'),known_aliases=[a])
        self.assertEqual(a.canonical_key,renamed.canonical_key)

    def test_network_scopes_are_separate_and_delivery_does_not_change_identity(self):
        make=lambda scope:resolve_identity(IdentityInput('a','splunk','one','IPAddress','10.0.0.1',scope=scope))
        self.assertNotEqual(make('vpc-a').canonical_key,make('vpc-b').canonical_key)
        self.assertEqual(make('vpc-a'),make('vpc-a'))

    def test_alias_match_proposes_without_claiming_authority(self):
        trusted=resolve_identity(self.item(authority='asset-a'))
        untrusted=resolve_identity(self.item(),known_aliases=[trusted])
        self.assertFalse(untrusted.automatic)
        self.assertNotEqual(untrusted.canonical_key,trusted.canonical_key)
        self.assertEqual(untrusted.candidate_keys,(trusted.canonical_key,))
