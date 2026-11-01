# SOC ontology v1

The source is `soorin/ontology/soc_ontology_v1.yaml`, a JSON-compatible YAML document so validation has no third-party dependency. It defines 17 entity classes and 15 relation classes with stable keys, descriptions, domain/range, cardinality, temporal behavior, provenance requirement, inverse, attributes, and confidence policy.

## Runtime import

`soorin/ontology/importer.py` validates the policy file, fetches the selected KB's authenticated ontology view, and produces a dry-run plan. Apply requires an explicit base URL, KB ID, token, and `--apply`. It creates only absent types, refuses label/temporal conflicts, never deletes or updates existing types, and verifies the resulting ontology.

```bash
python3 -m soorin.ontology.importer \
  --base-url http://127.0.0.1:2516 \
  --kb-id '<isolated-test-kb-uuid>' \
  --token '<editor-session-or-supported-bearer>'

# Re-run with --apply only after reviewing the preview.
```

Do not use `Soorin SOC Lab` for automatic testing. Native Utopia OWL import remains available for RDF/OWL vocabularies; the Soorin importer uses ontology CRUD because the domain policy contains operational fields not represented by Utopia's OWL projection.

Key semantic safeguards:

- `CORRELATED_WITH` never means identity.
- `DETECTED_BY` may carry a rule version/configuration time.
- `SUPPORTED_BY` requires evidence provenance.
- `HAD_IP` is temporal and network scoped.
- `SUPERSEDES` is explicit only.
- Similarity/risk scores never mean malicious probability.
