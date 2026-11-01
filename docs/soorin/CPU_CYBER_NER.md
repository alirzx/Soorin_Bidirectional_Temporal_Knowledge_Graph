# Optional CPU cybersecurity NER

**Default model:** [bnsapa/cybersecurity-ner](https://huggingface.co/bnsapa/cybersecurity-ner)

- Model family: English DistilBERT token classification, **66.4M parameters**.
- Model license: **Apache-2.0** (verify any upstream dependencies before distribution).
- Reported held-out F1: **0.7933** on the author's dataset. The card provides insufficient information about SOC-specific generalization. This is **not** a validated precision/recall estimate for Splunk notables, NOC traffic, or Persian prose.
- Default runtime: **disabled**, no download, **CPU-only**, local files only.
- Purpose: enrich **unstructured English security prose only**. Structured Alert, Notable, Host, User, IP, MITRE and other source IDs are extracted deterministically; NER proposals do **not** generate trusted graph identities.

Implementation: `soorin/extraction/cpu_cyber_ner.py`. The model is instantiated on first `extract()` call. The `transformers` and PyTorch dependencies are intentionally optional and should be installed into a dedicated CPU-oriented venv/container, **not** the base Rust Utopia Docker image.

For local evaluation **after explicitly downloading and reviewing the model artifacts** in an approved environment:

```python
from soorin.extraction.cpu_cyber_ner import CpuCyberNer
ner = CpuCyberNer(local_files_only=True)
proposals = ner.extract("Suspicious malware activity was reported on a test system")
for item in proposals:
    print(item.entity_type, item.value, item.score)
```

The published token-classification labels are mapped conservatively to the existing SOC ontology, and unknown labels are discarded. Mapping to `Host` or `Indicator` is **only a proposal**. Human/source validation is required. The model is not trained to produce authoritative SOC Alert IDs or exact host identities.

**Operational constraints:** no automatic model download at startup, configurable threshold and text limit, CPU device `-1`, no external inference API, no production-sensitive test material, and no implicit GPU use. Use a pinned, reviewed model revision for reproducible deployments; the current `local` marker is not an immutable Hub revision. Benchmark CPU latency and NER quality with representative synthetic samples before enabling the model in a live pipeline.

**Readiness:** Adapter and mock tests exist; actual CPU inference, model artifacts, and compatibility with installed Transformers/PyTorch are **unverified** in this branch.
