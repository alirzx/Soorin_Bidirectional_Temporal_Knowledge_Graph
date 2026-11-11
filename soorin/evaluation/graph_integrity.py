"""Graph-contract integrity checks with machine-readable reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import argparse
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from soorin.adapters.splunk import normalize_llm_payload
from soorin.adapters.utopia import StatementsAdapter, StatementsError
from soorin.contracts import SecurityKnowledgeEvent, validate_event_batch
from soorin.ontology import load_and_validate


@dataclass(frozen=True, slots=True)
class IntegrityReport:
    schema_version: str
    event_count: int
    entity_count: int
    relation_count: int
    statement_count: int
    exact_replays: int
    changed_revisions: int
    failures: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not self.failures

    def to_json(self) -> str:
        return json.dumps(asdict(self) | {"passed": self.passed}, sort_keys=True, indent=2)


def evaluate(events: Iterable[SecurityKnowledgeEvent], *, ontology_path: Path | None = None) -> IntegrityReport:
    rows = list(events)
    failures: list[str] = []
    if ontology_path:
        try:
            load_and_validate(ontology_path)
        except Exception as exc:
            failures.append(f"ontology:{exc}")
    adapter = StatementsAdapter()
    statement_count = 0
    for event in rows:
        try:
            payload = adapter.render(event)
            statement_count += len(payload["s"])
        except StatementsError as exc:
            failures.append(f"event:{event.event_id}:{exc.code}")
    duplicates = validate_event_batch(rows)
    return IntegrityReport(
        schema_version="soorin.soc.graph-integrity-report.v1", event_count=len(rows),
        entity_count=sum(len(event.entities) for event in rows),
        relation_count=sum(len(event.relations) for event in rows), statement_count=statement_count,
        exact_replays=sum(item.disposition == "exact_replay" for item in duplicates),
        changed_revisions=sum(item.disposition == "changed_revision" for item in duplicates),
        failures=tuple(failures),
    )


def load_synthetic_fixture(path: Path) -> list[SecurityKnowledgeEvent]:
    """Normalize a labeled synthetic Agentic-SOC fixture for offline evaluation."""

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping) or value.get("synthetic") is not True:
        raise ValueError("evaluation fixture must be an object labeled synthetic=true")
    records = value.get("records")
    if not isinstance(records, list):
        raise ValueError("evaluation fixture records must be an array")
    events: list[SecurityKnowledgeEvent] = []
    for index, row in enumerate(records):
        if not isinstance(row, Mapping):
            raise ValueError(f"records[{index}] must be an object")
        raw = row.get("raw_record")
        if not isinstance(raw, Mapping):
            raise ValueError(f"records[{index}].raw_record must be an object")
        normalized = normalize_llm_payload(
            row.get("llm_payload"),
            tenant_id=str(row.get("tenant_id", "")),
            source_instance=str(row.get("source_instance", "")),
            raw_record=raw,
            observed_at="2026-11-01T00:00:00Z",
        )
        events.append(normalized.event)
    return events


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate synthetic SOC graph inputs")
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--ontology", type=Path, default=Path(__file__).resolve().parents[1] / "ontology" / "soc_ontology_v1.yaml")
    args = parser.parse_args(argv)
    try:
        report = evaluate(load_synthetic_fixture(args.fixture), ontology_path=args.ontology)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(report.to_json())
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
