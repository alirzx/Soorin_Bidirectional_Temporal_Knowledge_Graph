"""Validate, preview, and safely apply the SOC ontology through Utopia APIs.

The committed ``.yaml`` file is JSON-compatible YAML so it can be parsed with
the standard library. Apply is opt-in, targets an explicit KB, requires an
authenticated editor token, and refuses to update or delete existing types.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import argparse
import getpass
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Mapping
import urllib.error
import urllib.request

ONTOLOGY_VERSION = "soorin.soc.ontology.v1"
EXPECTED_ENTITY_TYPES = 17
EXPECTED_RELATION_TYPES = 15
KEY_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
CARDINALITIES = {
    "many_to_many", "many_to_one", "many_to_one_at_time", "one_to_many",
    "many_to_many_over_time",
}


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
    if len(entities) != EXPECTED_ENTITY_TYPES or len(relations) != EXPECTED_RELATION_TYPES:
        raise OntologyError(
            f"ontology must declare exactly {EXPECTED_ENTITY_TYPES} entity types and "
            f"{EXPECTED_RELATION_TYPES} relation types"
        )
    entity_keys = _unique_keys(entities, "entity type")
    relation_keys = _unique_keys(relations, "relation type")
    by_relation = {item["key"]: item for item in relations}
    for entity in entities:
        for side in ("parents", "disjoint"):
            values = entity.get(side, [])
            if not isinstance(values, list) or set(values) - entity_keys:
                raise OntologyError(f"{entity.get('key')} has invalid {side}: {values!r}")
    for relation in relations:
        for side in ("domains", "ranges"):
            values = relation.get(side)
            if not isinstance(values, list) or not values or set(values) - entity_keys:
                raise OntologyError(f"{relation.get('key')} has invalid {side}: {values!r}")
        if relation.get("temporal") not in {"event", "state"}:
            raise OntologyError(f"{relation.get('key')} has invalid temporal behavior")
        if relation.get("cardinality") not in CARDINALITIES:
            raise OntologyError(f"{relation.get('key')} has invalid cardinality")
        if not isinstance(relation.get("confidence_policy"), str) or not relation["confidence_policy"].strip():
            raise OntologyError(f"{relation.get('key')} must declare confidence_policy")
        attributes = relation.get("attributes")
        if not isinstance(attributes, list) or not all(isinstance(value, str) and value for value in attributes):
            raise OntologyError(f"{relation.get('key')} has invalid attributes")
        inverse = relation.get("inverse")
        if inverse is not None and inverse not in relation_keys:
            raise OntologyError(f"{relation.get('key')} references unknown inverse {inverse}")
        if inverse is not None and by_relation[inverse].get("inverse") != relation["key"]:
            raise OntologyError(f"{relation.get('key')} inverse {inverse} is not reciprocal")
        if relation.get("required_provenance") is not True:
            raise OntologyError(f"{relation.get('key')} must require provenance")
    return data


def _unique_keys(items: list[Mapping[str, Any]], kind: str) -> set[str]:
    keys: list[str] = []
    for item in items:
        key = item.get("key")
        if (
            not isinstance(key, str) or not KEY_RE.fullmatch(key)
            or not isinstance(item.get("label"), str) or not item["label"].strip()
            or not isinstance(item.get("description"), str) or not item["description"].strip()
        ):
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


def _lower_camel(label: str) -> str:
    """Match Utopia's ontology label normalization exactly."""

    out: list[str] = []
    start_of_word = False
    for char in label.strip():
        if char in " _-":
            start_of_word = bool(out)
            continue
        if not out:
            out.append(char.lower())
        elif start_of_word:
            out.append(char.upper())
            start_of_word = False
        else:
            out.append(char)
    return "".join(out)


def _entity_expected(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "key": item["key"], "label": item["label"], "description": item["description"],
        "color": item.get("color", "#8ea5bd"), "shape": item.get("shape", "circle"),
        "builtin": False, "parents": list(item.get("parents", [])),
        "primary_parent": None, "disjoint": list(item.get("disjoint", [])),
    }


def _relation_expected(item: Mapping[str, Any], relation_ids: Mapping[str, str]) -> dict[str, Any]:
    inverse = item.get("inverse")
    return {
        "key": item["key"], "label": _lower_camel(item["label"]),
        "description": item["description"], "temporal": item["temporal"], "kind": "relation",
        "functional": item["cardinality"] in {"many_to_one", "many_to_one_at_time"},
        "inverse_functional": item["cardinality"] == "one_to_many",
        "is_transitive": False, "is_symmetric": inverse == item["key"],
        "is_asymmetric": False, "is_irreflexive": False,
        "inverse_of": relation_ids.get(inverse) if inverse else None,
        "sub_property_of": None, "builtin": False,
        "domains": list(item["domains"]), "ranges": list(item["ranges"]),
        "qualifiers": [], "datatype": None, "unit": None,
    }


def _different(actual: Mapping[str, Any], expected: Mapping[str, Any]) -> list[str]:
    return [key for key, value in expected.items() if actual.get(key) != value]


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
        entity_id_to_key = {str(item.get("id")): str(item.get("key")) for item in current.get("entity_types", [])}
        relation_id_to_key = {str(item.get("id")): str(item.get("key")) for item in current.get("relation_types", [])}
        relation_key_to_id = {key: identifier for identifier, key in relation_id_to_key.items()}
        for item in ontology["entity_types"]:
            existing = existing_entities.get(item["key"])
            if existing is None:
                create_e.append(item["key"])
            else:
                actual = dict(existing)
                actual["parents"] = sorted(entity_id_to_key.get(str(value), str(value)) for value in existing.get("parents", []))
                actual["disjoint"] = sorted(entity_id_to_key.get(str(value), str(value)) for value in existing.get("disjoint", []))
                expected = _entity_expected(item)
                expected["parents"] = sorted(expected["parents"])
                expected["disjoint"] = sorted(expected["disjoint"])
                changed = _different(actual, expected)
                if changed:
                    conflicts.append(f"entity:{item['key']}: fields differ: {','.join(changed)}")
                else:
                    same_e.append(item["key"])
        for item in ontology["relation_types"]:
            existing = existing_relations.get(item["key"])
            if existing is None:
                create_r.append(item["key"])
            else:
                actual = dict(existing)
                for field in ("domains", "ranges"):
                    actual[field] = sorted(entity_id_to_key.get(str(value), str(value)) for value in existing.get(field, []))
                actual["qualifiers"] = sorted(str(value) for value in existing.get("qualifiers", []))
                actual["inverse_of"] = relation_id_to_key.get(str(existing.get("inverse_of"))) if existing.get("inverse_of") else None
                actual["sub_property_of"] = relation_id_to_key.get(str(existing.get("sub_property_of"))) if existing.get("sub_property_of") else None
                expected = _relation_expected(item, {key: key for key in relation_key_to_id})
                expected["domains"] = sorted(expected["domains"])
                expected["ranges"] = sorted(expected["ranges"])
                expected["inverse_of"] = item.get("inverse")
                changed = _different(actual, expected)
                if changed:
                    conflicts.append(f"relation:{item['key']}: fields differ: {','.join(changed)}")
                else:
                    same_r.append(item["key"])
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
                "color": item.get("color", "#8ea5bd"), "shape": item.get("shape", "circle"),
                "parents": list(item.get("parents", [])), "disjoint": list(item.get("disjoint", [])),
            })
            if not response.get("id"):
                raise OntologyError(f"missing id after creating entity type {item['key']}")
            entity_ids[item["key"]] = str(response["id"])
        relation_ids = {str(item["key"]): str(item["id"]) for item in current.get("relation_types", [])}
        created_relations: set[str] = set()
        for item in ontology["relation_types"]:
            if item["key"] in relation_ids:
                continue
            expected = _relation_expected(item, relation_ids)
            response = self._call("POST", "/ontology/relation-types", {
                **expected, "label": item["label"],
                "domains": [entity_ids[key] for key in item["domains"]],
                "ranges": [entity_ids[key] for key in item["ranges"]],
                "inverse_of": None,
            })
            if not response.get("id"):
                raise OntologyError(f"missing id after creating relation type {item['key']}")
            relation_ids[item["key"]] = str(response["id"])
            created_relations.add(item["key"])
        # Inverse pairs are often cyclic, so link them only after every new
        # relation has an API id. Existing relations are never modified.
        for item in ontology["relation_types"]:
            if item["key"] not in created_relations or not item.get("inverse"):
                continue
            expected = _relation_expected(item, relation_ids)
            self._call("PATCH", f"/ontology/relation-types/{relation_ids[item['key']]}", {
                **expected,
                "domains": [entity_ids[key] for key in item["domains"]],
                "ranges": [entity_ids[key] for key in item["ranges"]],
            })
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
    parser.add_argument("--token-env", default="UTOPIA_ACCESS_TOKEN", help="Environment variable containing the bearer token")
    parser.add_argument("--prompt-token", action="store_true", help="Read the bearer token securely from the terminal")
    parser.add_argument("--apply", action="store_true", help="Apply after preview; omitted means dry-run")
    args = parser.parse_args(argv)
    ontology = load_and_validate(args.ontology)
    token = os.environ.get(args.token_env, "").strip()
    if not token and args.prompt_token:
        token = getpass.getpass("Utopia access token: ").strip()
    if not token:
        parser.error(f"missing bearer token in {args.token_env}; use --prompt-token for secure entry")
    importer = OntologyImporter(args.base_url, args.kb_id, token)
    preview = importer.preview(ontology)
    print(json.dumps(asdict(preview), sort_keys=True, indent=2))
    if args.apply:
        importer.apply(ontology)
        print("Ontology applied and verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
