# Optional CPU cybersecurity NER

**Default model:** [bnsapa/cybersecurity-ner](https://huggingface.co/bnsapa/cybersecurity-ner)

**Reviewed immutable revision:** `1ad52f1a7686a58da2a427c0706d8b868df47181`

- Model family: English DistilBERT token classification, **66.4M parameters**.
- Model license: **Apache-2.0** (verify any upstream dependencies before distribution).
- Reported held-out F1: **0.7933** on the author's dataset. The card provides insufficient information about SOC-specific generalization. This is **not** a validated precision/recall estimate for Splunk notables, NOC traffic, or Persian prose.
- Default runtime: **disabled**, no download, **CPU-only**, local files only.
- Purpose: enrich **unstructured English security prose only**. Structured Alert, Notable, Host, User, IP, MITRE and other source IDs are extracted deterministically; NER proposals do **not** generate trusted graph identities.

Implementation: `soorin/extraction/cpu_cyber_ner.py`. The model is instantiated on first `extract()` call. The `transformers` and PyTorch dependencies are intentionally optional and should be installed into a dedicated CPU-oriented venv/container, **not** the base Rust Utopia Docker image.

Install the reviewed CPU dependency range explicitly with `python -m pip install -r soorin/requirements-ner-cpu.txt`. Choose the PyTorch CPU wheel/index appropriate for the deployment platform; the requirements file intentionally does not force a CUDA build.

For local evaluation **after explicitly downloading and reviewing the model artifacts** in an approved environment:

```python
from soorin.extraction.cpu_cyber_ner import CpuCyberNer
ner = CpuCyberNer(local_files_only=True)
proposals = ner.extract("Suspicious malware activity was reported on a test system")
for item in proposals:
    print(item.entity_type, item.value, item.score)
```

The published config exposes `Indicator`, `Malware`, `Organization`, `System`, and `Vulnerability` BIO labels, but the model card does not define their annotation semantics. `Indicator`, `Malware`, and `Vulnerability` spans become generic `Indicator` proposals with the original `source_label` preserved. `Organization` and `System` are discarded: mapping them to an ontology `Host` or another trusted type would be an unsupported semantic claim. Every proposal has `review_required=True`; the model is not trained to produce authoritative SOC Alert IDs or exact host identities.

`soorin.extraction.enrich_entities()` is the supported integration boundary. It runs deterministic structured/regex extraction first, sends only fields explicitly classified as unstructured to the optional provider, removes proposals already covered by deterministic output, and returns proposals in a separate collection. It never writes identities or facts.

**Operational constraints:** no automatic model download at startup, configurable threshold and text limit, CPU device `-1`, no external inference API, no production-sensitive test material, and no implicit GPU use. Persian/Arabic-script input returns no proposals because the checkpoint is documented as English-only. The default model load is pinned to the reviewed revision above and requires local model files in operational mode. Benchmark CPU latency and NER quality with representative synthetic samples before enabling the model in a live pipeline.

**Readiness:** Adapter and mock tests exist; actual CPU inference, model artifacts, and compatibility with installed Transformers/PyTorch are **unverified** in this branch.
