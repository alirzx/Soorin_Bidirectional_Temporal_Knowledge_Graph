"""Optional, lazy, CPU-only cybersecurity NER enrichment.

Model: bnsapa/cybersecurity-ner (Apache-2.0, English DistilBERT).
Proposals are *not* authoritative identities or graph facts. No model download,
GPU allocation or third-party network calls happen at import/startup.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

DEFAULT_NER_MODEL = "bnsapa/cybersecurity-ner"
DEFAULT_NER_MIN_SCORE = 0.80
# Model labels from its published token-classification config. Keep proposed
# types to known domain ontology categories; unsupported labels are ignored.
LABEL_MAP = {
    "INDICATOR": "Indicator",
    "MALWARE": "Indicator",
    "VULNERABILITY": "Indicator",
    "SYSTEM": "Host",
    "ORGANIZATION": "Indicator",
}


@dataclass(frozen=True, slots=True)
class NerProposal:
    entity_type: str
    value: str
    score: float
    model_version: str


class NerProvider(Protocol):
    def extract(self, text: str) -> list[NerProposal]: ...


class DisabledNer:
    def extract(self, text: str) -> list[NerProposal]:
        return []


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
    model_revision: str = "local"

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
                self.model, local_files_only=self.local_files_only,
                trust_remote_code=False,
            )
            model = AutoModelForTokenClassification.from_pretrained(
                self.model, local_files_only=self.local_files_only,
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
        classifier = self._load()
        rows = classifier(text[:self.max_chars], truncation=True)
        if not isinstance(rows, list):
            raise ValueError("NER provider returned invalid result")
        proposals: list[NerProposal] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            label = str(row.get("entity_group", row.get("entity", ""))).upper()
            if label.startswith(("B-", "I-")):
                label = label[2:]
            kind = LABEL_MAP.get(label)
            value = row.get("word")
            score = row.get("score", 0.0)
            if kind is None or not isinstance(value, str) or not value.strip():
                continue
            if not isinstance(score, (float, int)) or not self.min_score <= float(score) <= 1:
                continue
            proposals.append(NerProposal(kind, value.strip(), float(score),
                                         f"{self.model}@{self.model_revision}"))
        return proposals
