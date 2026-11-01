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
  --token '<test-only-editor-token>'
```

**Security warning:** `--token` places the credential in the process argument list and, if written literally into a shell command, may expose it through shell history. **Do not use this CLI with production tokens**. Refactor the importer to accept protected token input or a secret store before live operational use. The above syntax is documented only to describe the current implementation. Do not paste real credentials into command histories or CI logs.

The `--apply` flag performs writes; leave it off for preview. Never run against the existing `Soorin SOC Lab` during automatic testing. An isolated test KB and authenticated role are required.

## Model and provenance semantics

- `CORRELATED_WITH` represents correlation, never entity identity.
- `DETECTED_BY` may contain rule version/configuration time; the current rule configuration is not necessarily fire-time evidence.
- `SUPPORTED_BY` must point to recoverable evidence.
- `HAD_IP` is time- and network-scope-aware.
- `SUPERSEDES` requires an explicit source assertion.
- Embedding similarity and vendor risk scores are ranking/risk signals, not malicious probabilities.

The current importer **does not yet compare all pre-existing domain/range, axiom, cardinality and provenance policies**, so an apparently successful preview may miss semantic conflicts. See [P0 gaps](SOC_FOUNDATION_GAP_ANALYSIS.md).

## Acceptance before merge

1. Validate ontology declarations and inverse signatures.
2. Refuse conflicts across *all* enforceable relation fields; flag policy-only fields clearly.
3. Preview and apply to a disposable KB using a protected token.
4. Verify persisted entity and relation types via authenticated Utopia API.
5. Ingest a synthetic event, run alignment jobs and verify **typed graph materialization**, not merely an import acknowledgment.
