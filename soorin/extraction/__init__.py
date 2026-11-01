"""SOC entity extraction with deterministic-first behavior."""

from .deterministic import ExtractionBatch, ExtractionResult, extract_entities

__all__ = ["ExtractionBatch", "ExtractionResult", "extract_entities"]
