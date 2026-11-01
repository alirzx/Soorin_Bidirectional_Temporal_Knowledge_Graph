"""Validate, preview, and safely apply the SOC ontology through Utopia APIs.

The committed ``.yaml`` file is JSON-compatible YAML so it can be parsed with
the standard library. Apply is opt-in, targets an explicit KB, requires an
authenticated editor token, and refuses to update or delete existing types.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import argparse
import json
from pathlib import Path
from typing import Any, Callable, Mapping
import urllib.error
import urllib.request

ONTOLOGY_VERSION = "soorin.soc.ontology.v1"


class OntologyError(ValueError):
    pass


def load_and_validate(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OntologyError(f"cannot read ontology: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != ONTOLOGY_VERSION:
        raise OntologyError(f"schema_version must be {ONTOLOGY_VERSION}")
    entities = data.get("entity_types")
    relations = data.get("relation_types")
    if not isinstance(entities, list) or not entities or not isinstance(relations, list) or not relations:
        raise OntologyError("entity_types and relation_types must be nonempty arrays")
    entity_keys = _unique_keys(entities, "entity type")
    relation_keys = _unique_keys(relations, "relation type")
    for relation in relations:
        for side in ("domains", "ranges"):
            values = relation.get(side)
            if not isinstance(values, list) or not values or set(values) - entity_keys:
                raise OntologyError(f"{relation.get('key')} has invalid {side}: {values!r}")
        if relation.get("temporal") not in {"event", "state"}:
            raise OntologyError(f"{relation.get('key')} has invalid temporal behavior")
        inverse = relation.get("inverse")
        if inverse is not None and inverse not in relation_keys:
            raise OntologyError(f"{relation.get('key')} references unknown inverse {inverse}")
        if relation.get("required_provenance") is not True:
            raise OntologyError(f"{relation.get('key')} must require provenance")
    return data


def _unique_keys(items: list[Mapping[str, Any]], kind: str) -> set[str]:
    keys: list[str] = []
    for item in items:
        key = item.get("key")
        if not isinstance(key, str) or not key or not isinstance(item.get("label"), str) or not item.get("description"):
            raise OntologyError(f"every {kind} needs key, label and description")
        keys.append(key)
    if len(keys) != len(set(keys)):
        raise OntologyError(f"duplicate {kind} key")
    return set(keys)


@dataclass(frozen=True, slots=True)
class ImportPreview:
    create_entity_types: tuple[str, ...]
    create_relation_types: tuple[str, ...]
    unchanged_entity_types: tuple[str, ...]
    unchanged_relation_types: tuple[str, ...]
    conflicts: tuple[str, ...]

    @property
    def safe_to_apply(self) -> bool:
        return not self.conflicts


Request = Callable[[str, str, Mapping[str, Any] | None], Mapping[str, Any]]


@dataclass(slots=True)
class OntologyImporter:
    base_url: str
    kb_id: str
    token: str
    request: Request | None = None

    def _call(self, method: str, path: str, body: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        if self.request:
            return self.request(method, path, body)
        url = f"{self.base_url.rstrip('/')}/api/v1/kbs/{self.kb_id}{path}"
        payload = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url, data=payload, method=method,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                value = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read(2048).decode("utf-8", errors="replace")
            raise OntologyError(f"Utopia HTTP {exc.code}: {detail}") from exc
        if not isinstance(value, Mapping):
            raise OntologyError("Utopia returned a non-object response")
        return value

    def current(self) -> Mapping[str, Any]:
        return self._call("GET", "/ontology")

    def preview(self, ontology: Mapping[str, Any], current: Mapping[str, Any] | None = None) -> ImportPreview:
        current = current or self.current()
        existing_entities = {str(item.get("key")): item for item in current.get("entity_types", [])}
        existing_relations = {str(item.get("key")): item for item in current.get("relation_types", [])}
        create_e: list[str] = []
        same_e: list[str] = []
        create_r: list[str] = []
        same_r: list[str] = []
        conflicts: list[str] = []
        for item in ontology["entity_types"]:
            existing = existing_entities.get(item["key"])
            if existing is None:
                create_e.append(item["key"])
            elif str(existing.get("label")) == item["label"]:
                same_e.append(item["key"])
            else:
                conflicts.append(f"entity:{item['key']}: existing label differs")
        for item in ontology["relation_types"]:
            existing = existing_relations.get(item["key"])
            if existing is None:
                create_r.append(item["key"])
            elif str(existing.get("label")) == item["label"] and str(existing.get("temporal")) == item["temporal"]:
                same_r.append(item["key"])
            else:
                conflicts.append(f"relation:{item['key']}: existing definition differs")
        return ImportPreview(tuple(create_e), tuple(create_r), tuple(same_e), tuple(same_r), tuple(conflicts))

    def apply(self, ontology: Mapping[str, Any]) -> ImportPreview:
        current = self.current()
        preview = self.preview(ontology, current)
        if not preview.safe_to_apply:
            raise OntologyError("refusing to overwrite existing ontology: " + "; ".join(preview.conflicts))
        entity_ids = {str(item["key"]): str(item["id"]) for item in current.get("entity_types", [])}
        for item in ontology["entity_types"]:
            if item["key"] in entity_ids:
                continue
            response = self._call("POST", "/ontology/entity-types", {
                "key": item["key"], "label": item["label"], "description": item["description"],
                "shape": "circle", "parents": [],
            })
            if not response.get("id"):
                raise OntologyError(f"missing id after creating entity type {item['key']}")
            entity_ids[item["key"]] = str(response["id"])
        existing_relations = {str(item.get("key")) for item in current.get("relation_types", [])}
        for item in ontology["relation_types"]:
            if item["key"] in existing_relations:
                continue
            response = self._call("POST", "/ontology/relation-types", {
                "key": item["key"], "label": item["label"], "description": item["description"],
                "temporal": item["temporal"], "kind": "relation",
                "domains": [entity_ids[key] for key in item["domains"]],
                "ranges": [entity_ids[key] for key in item["ranges"]],
                "functional": item["cardinality"] in {"many_to_one", "many_to_one_at_time"},
                "inverse_functional": False, "is_transitive": False,
                "is_symmetric": item.get("inverse") == item["key"],
                "is_asymmetric": False, "is_irreflexive": False,
            })
            if not response.get("id"):
                raise OntologyError(f"missing id after creating relation type {item['key']}")
        verified = self.current()
        final_preview = self.preview(ontology, verified)
        if final_preview.create_entity_types or final_preview.create_relation_types or final_preview.conflicts:
            raise OntologyError("post-apply verification failed")
        return final_preview


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ontology", type=Path, default=Path(__file__).with_name("soc_ontology_v1.yaml"))
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--kb-id", required=True, help="Explicit isolated test KB identifier")
    parser.add_argument("--token", required=True)
    parser.add_argument("--apply", action="store_true", help="Apply after preview; omitted means dry-run")
    args = parser.parse_args(argv)
    ontology = load_and_validate(args.ontology)
    importer = OntologyImporter(args.base_url, args.kb_id, args.token)
    preview = importer.preview(ontology)
    print(json.dumps(asdict(preview), sort_keys=True, indent=2))
    if args.apply:
        importer.apply(ontology)
        print("Ontology applied and verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
