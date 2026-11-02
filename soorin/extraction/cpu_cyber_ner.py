"""Optional, lazy, CPU-only cybersecurity NER enrichment.

Model: bnsapa/cybersecurity-ner (Apache-2.0, English DistilBERT).
Proposals are *not* authoritative identities or graph facts. No model download,
GPU allocation or third-party network calls happen at import/startup.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Callable

from .ner import DisabledNer, NerProposal

DEFAULT_NER_MODEL = "bnsapa/cybersecurity-ner"
DEFAULT_NER_REVISION = "1ad52f1a7686a58da2a427c0706d8b868df47181"
DEFAULT_NER_MIN_SCORE = 0.80
# The reviewed model config publishes these labels without semantic
# definitions. Malware/vulnerability/indicator spans can only be represented
# as generic Indicator proposals in the current ontology, with source_label
# retained. Organization and System are ignored: mapping either to a trusted
# SOC type would invent semantics not supported by the model card.
LABEL_MAP = {
    "INDICATOR": "Indicator",
    "MALWARE": "Indicator",
    "VULNERABILITY": "Indicator",
}
UNSUPPORTED_SCRIPT_RE = re.compile(r"[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff]")


@dataclass(slots=True)
class CpuCyberNer:
    """Optional model enrichment for unstructured English SOC prose only.

    Install extras explicitly. Set local_files_only=True in operational mode.
    Inject a token classifier for fast offline tests. Model initialization is
    lazy; failures are visible and never silently trigger network downloads.
    """
    model: str = DEFAULT_NER_MODEL
    min_score: float = DEFAULT_NER_MIN_SCORE
    max_chars: int = 4000
    local_files_only: bool = True
    classifier: Callable[..., Any] | None = field(default=None, repr=False)
    model_revision: str = DEFAULT_NER_REVISION

    def __post_init__(self) -> None:
        if not 0.0 <= self.min_score <= 1.0:
            raise ValueError("NER min_score must be in [0, 1]")
        if not 1 <= self.max_chars <= 100000:
            raise ValueError("NER max_chars must be positive")

    def _load(self) -> Callable[..., Any]:
        if self.classifier is None:
            try:
                from transformers import AutoModelForTokenClassification, AutoTokenizer, pipeline
            except ImportError as exc:
                raise RuntimeError("CPU NER requires optional transformers and torch dependencies") from exc
            tokenizer = AutoTokenizer.from_pretrained(
                self.model, revision=self.model_revision, local_files_only=self.local_files_only,
                trust_remote_code=False,
            )
            model = AutoModelForTokenClassification.from_pretrained(
                self.model, revision=self.model_revision, local_files_only=self.local_files_only,
                trust_remote_code=False, use_safetensors=True,
            )
            self.classifier = pipeline(
                "token-classification", model=model, tokenizer=tokenizer,
                aggregation_strategy="simple", device=-1,
            )
        return self.classifier

    def extract(self, text: str) -> list[NerProposal]:
        if not isinstance(text, str) or not text.strip():
            return []
        # This checkpoint is documented as English-only. Returning no proposal
        # is safer than attaching English-label semantics to Persian/Arabic.
        if UNSUPPORTED_SCRIPT_RE.search(text):
            return []
        classifier = self._load()
        rows = classifier(text[:self.max_chars], truncation=True)
        if not isinstance(rows, list):
            raise ValueError("NER provider returned invalid result")
        proposals: dict[tuple[str, str, str], NerProposal] = {}
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError(f"NER provider row {index} is not an object")
            label = str(row.get("entity_group", row.get("entity", ""))).upper()
            if label.startswith(("B-", "I-")):
                label = label[2:]
            kind = LABEL_MAP.get(label)
            value = row.get("word")
            score = row.get("score", 0.0)
            if kind is None or not isinstance(value, str) or not value.strip():
                continue
            if isinstance(score, bool) or not isinstance(score, (float, int)):
                raise ValueError(f"NER provider row {index} has an invalid score")
            score = float(score)
            if not 0.0 <= score <= 1.0:
                raise ValueError(f"NER provider row {index} has an invalid score")
            if score < self.min_score:
                continue
            proposal = NerProposal(
                kind, value.strip(), score, f"{self.model}@{self.model_revision}",
                source_label=label, review_required=True,
            )
            key = kind, proposal.value.casefold(), label
            if key not in proposals or score > proposals[key].score:
                proposals[key] = proposal
        return sorted(proposals.values(), key=lambda item: (item.entity_type, item.value.casefold(), item.source_label or ""))
