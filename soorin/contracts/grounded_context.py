"""Versioned read-only context and citation validation for future SOC agents."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Mapping
import json


@dataclass(frozen=True)
class GroundedClaim:
    text: str
    fact_ids: tuple[str, ...]


def validate_claims(context: Mapping[str, Any], claims: list[GroundedClaim]) -> None:
    if context.get("schema_version") != "soorin.knowledge-context.v2":
        raise ValueError("unsupported knowledge context")
    facts = {str(row["id"]): row for row in context.get("facts", [])}
    cited = {str(row["fact_id"]) for row in context.get("evidence_references", [])}
    for claim in claims:
        if not claim.text.strip() or not claim.fact_ids:
            raise ValueError("every claim requires cited facts")
        for fact_id in claim.fact_ids:
            if fact_id not in facts or fact_id not in cited:
                raise ValueError("unsupported claim or missing source evidence")
            if facts[fact_id].get("contested"):
                raise ValueError("contested evidence requires explicit review")


def extractive_answer(context: Mapping[str, Any]) -> dict[str, Any]:
    """Return ledger statements with citations; never ask a model to invent facts."""
    cited = {str(row["fact_id"]) for row in context.get("evidence_references", [])}
    claims = []
    for fact in context.get("facts", []):
        identifier = str(fact["id"])
        if identifier in cited and not fact.get("contested"):
            claims.append({"fact_id": identifier, "predicate": fact.get("predicate_key"),
                "object": fact.get("object_value", fact.get("other_name")), "citation": identifier,
                "assertion_origin": "open" if fact.get("inferred") else "typed"})
    return {"schema_version": "soorin.grounded-answer.v1", "claims": claims,
        "status": "complete" if claims else "unavailable", "generated": False}
