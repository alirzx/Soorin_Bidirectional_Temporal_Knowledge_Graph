from dataclasses import replace
import json
from pathlib import Path
import unittest
from soorin.contracts import SecurityKnowledgeEvent
from soorin.contracts.native_profile import validate_native_event
from soorin.contracts.storage_policy import minimize

class NativeProfileTests(unittest.TestCase):
    def event(self):
        return SecurityKnowledgeEvent.from_dict(json.loads((Path(__file__).parents[1] / 'fixtures/soc_canonical_minimal_v1.json').read_text())['event'])

    def test_current_fixture_is_native_and_proposals_require_review(self):
        event = self.event()
        validate_native_event(event)
        invalid = replace(event, entities=(replace(event.entities[0], provisional='false'),), content_checksum=None)
        with self.assertRaises(ValueError):
            validate_native_event(invalid)

    def test_sensitive_extensions_require_explicit_policy(self):
        event = replace(self.event(), vendor_fields={'private': 'synthetic'}, content_checksum=None)
        with self.assertRaises(ValueError):
            validate_native_event(event)
        validate_native_event(event, allow_sensitive=True)
        self.assertEqual(minimize({'safe': {'_raw': 'private', 'id': 'e1'}, 'password': 'private'}), {'safe': {'id': 'e1'}})
