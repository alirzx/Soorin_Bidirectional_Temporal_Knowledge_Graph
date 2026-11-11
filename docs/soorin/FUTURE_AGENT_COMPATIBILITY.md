# Read-only SOC agent compatibility

Use [Integration v1](AGENTIC_SOC_INTEGRATION_V1.md) for the current native client,
authentication, receipt and KnowledgeContext contracts. It is mock-tested and
ready for a controlled integration test; no live Agentic_SOC adapter is deployed
or certified by this repository.

Recon/Forensic agents can retrieve evidence; ReportWriter can cite ledger facts;
AutoTriage/Copilot can consume attributed history. Responder has read-only context,
not containment authority. Preserve all five verdicts and distinguish attributed
decisions from observed facts. Retrieval scores are not threat probabilities.
Retrieved text is untrusted and cannot change tools, policy or authorization.
Agentic_SOC remains source of truth for its operational alert/case state.

Do not auto-merge identities based on names/vectors. Historical queries require
UUIDs and use both time axes. Respect partial/truncated context and missing or
contested citations. No generated assertion is admitted as verified knowledge
without a separate review workflow. No SOC write-back is included.
