from __future__ import annotations

from pathlib import Path
import unittest

from soorin.ontology.importer import OntologyError, OntologyImporter, load_and_validate

ONTOLOGY = Path(__file__).resolve().parents[2] / "ontology" / "soc_ontology_v1.yaml"


class FakeApi:
    def __init__(self):
        self.entities = []
        self.relations = []
        self.calls = []

    def __call__(self, method, path, body):
        self.calls.append((method, path, body))
        if method == "GET":
            return {"entity_types": list(self.entities), "relation_types": list(self.relations)}
        if path.endswith("entity-types"):
            row = {**body, "id": f"e-{len(self.entities) + 1}", "builtin": False,
                   "primary_parent": None, "usage": 0}
            self.entities.append(row)
            return {"id": row["id"]}
        if method == "PATCH":
            identifier = path.rsplit("/", 1)[-1]
            row = next(item for item in self.relations if item["id"] == identifier)
            row.update(body)
            return {"ok": True}
        label = body["label"]
        words = label.replace("_", " ").replace("-", " ").split()
        normalized_label = words[0].lower() + "".join(word[:1].upper() + word[1:] for word in words[1:])
        row = {**body, "label": normalized_label, "id": f"r-{len(self.relations) + 1}",
               "builtin": False, "usage": 0}
        self.relations.append(row)
        return {"id": row["id"]}


class OntologyTests(unittest.TestCase):
    def test_ontology_validates_and_has_complete_signatures(self):
        ontology = load_and_validate(ONTOLOGY)
        self.assertGreaterEqual(len(ontology["entity_types"]), 17)
        self.assertGreaterEqual(len(ontology["relation_types"]), 15)
        self.assertTrue(all(item["required_provenance"] for item in ontology["relation_types"]))

    def test_preview_is_dry_run(self):
        ontology = load_and_validate(ONTOLOGY)
        fake = FakeApi()
        importer = OntologyImporter("http://test", "kb-test", "token", fake)
        preview = importer.preview(ontology)
        self.assertTrue(preview.safe_to_apply)
        self.assertEqual(len(fake.calls), 1)
        self.assertTrue(preview.create_entity_types)

    def test_apply_is_idempotent_and_verified(self):
        ontology = load_and_validate(ONTOLOGY)
        fake = FakeApi()
        importer = OntologyImporter("http://test", "kb-test", "token", fake)
        final = importer.apply(ontology)
        self.assertFalse(final.create_entity_types)
        self.assertFalse(final.create_relation_types)
        creates = len([call for call in fake.calls if call[0] == "POST"])
        importer.apply(ontology)
        self.assertEqual(creates, len([call for call in fake.calls if call[0] == "POST"]))

    def test_conflicting_existing_type_refuses_overwrite(self):
        ontology = load_and_validate(ONTOLOGY)
        fake = FakeApi()
        fake.entities.append({"id": "existing", "key": "host", "label": "Wrong Label"})
        importer = OntologyImporter("http://test", "kb-test", "token", fake)
        with self.assertRaisesRegex(OntologyError, "refusing to overwrite"):
            importer.apply(ontology)

    def test_semantic_conflict_is_not_hidden_by_matching_label(self):
        ontology = load_and_validate(ONTOLOGY)
        fake = FakeApi()
        importer = OntologyImporter("http://test", "kb-test", "token", fake)
        importer.apply(ontology)
        fake.relations[0]["functional"] = True
        preview = importer.preview(ontology)
        self.assertFalse(preview.safe_to_apply)
        self.assertIn("functional", " ".join(preview.conflicts))


if __name__ == "__main__":
    unittest.main()
