# Soorin SOC ontology v1

The ontology source is [`soorin/ontology/soc_ontology_v1.yaml`](../../soorin/ontology/soc_ontology_v1.yaml), a JSON-compatible YAML document so the Python validator has no external YAML dependency.

It declares **17 entity classes and 15 relation classes** with keys, descriptions, domain/range, temporal semantics, cardinality, inverse, expected provenance and confidence policies. **Declaration is not proof of runtime enforcement**: Utopia stores supported ontology fields; several Soorin policy fields are conventions requiring separate validation.

## Guarded importer: offline-tested, live verification pending

[`soorin/ontology/importer.py`](../../soorin/ontology/importer.py) implements validate, preview, authenticated create-only apply and post-apply verification. Tests use a fake API. It has **not** been tested against a live isolated Utopia KB.

Inspect current source and CLI help first:

```bash
python3 -m soorin.ontology.importer --help
```

Current CLI usage is:

```text
python3 -m soorin.ontology.importer \
  --base-url http://127.0.0.1:2516 \
  --kb-id '<isolated-test-kb-uuid>' \
  --token-env UTOPIA_ACCESS_TOKEN
```

Set the named variable from an approved secret source, or add `--prompt-token` to read it without echo. Never paste a token into a command line, shell history, report, or CI log.

The `--apply` flag performs writes; leave it off for preview. Never run against the existing `Soorin SOC Lab` during automatic testing. An isolated test KB and authenticated role are required.

## Model and provenance semantics

- `CORRELATED_WITH` represents correlation, never entity identity.
- `DETECTED_BY` may contain rule version/configuration time; the current rule configuration is not necessarily fire-time evidence.
- `SUPPORTED_BY` must point to recoverable evidence.
- `HAD_IP` is time- and network-scope-aware.
- `SUPERSEDES` requires an explicit source assertion.
- Embedding similarity and vendor risk scores are ranking/risk signals, not malicious probabilities.

## Enforcement status

| Declaration | Import/runtime status |
|---|---|
| Entity and relation keys, labels, descriptions | Validated locally; create-only importer compares persisted values and refuses conflicts |
| Domain and range | Imported into Utopia and used by signature consistency/errata checks; not a SQL foreign-key gate on every Statements row |
| `temporal` (`event`/`state`) | Imported and used by Utopia world-time and timeline reconciliation |
| `functional` / `inverse_functional` cardinality | Mapped from supported cardinalities and used by Utopia reasoning/temporal conflict handling; “at time” semantics still require live verification |
| Inverse and symmetric relation axioms | Imported into supported Utopia axiom fields and used by reasoning; reciprocal declarations are validated before apply |
| `required_provenance` | Soorin contract/adapter convention and offline assertion; not an ontology API field or universal database constraint |
| `confidence_policy` | Soorin validation/documentation convention; not imported as a Utopia axiom |
| Relation `attributes` | Documented expected qualifiers; not automatically created or required by this importer |

The importer compares every Utopia field it actually projects. A policy-only field cannot conflict at the ontology API because it is not represented there; its enforcement must remain in adapters, acceptance assertions, or a later runtime gate.

## Acceptance before merge

1. Validate ontology declarations and inverse signatures.
2. Refuse conflicts across *all* enforceable relation fields; flag policy-only fields clearly.
3. Preview and apply to a disposable KB using a protected token.
4. Verify persisted entity and relation types via authenticated Utopia API.
5. Ingest a synthetic event, run alignment jobs and verify **typed graph materialization**, not merely an import acknowledgment.
