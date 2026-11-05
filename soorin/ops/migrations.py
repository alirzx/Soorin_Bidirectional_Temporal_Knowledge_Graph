"""Read-only migration collision/checksum audit. Never renumbers applied SQL."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def manifest(root: Path) -> dict[int, dict[str, str]]:
    result = {}
    for path in sorted(root.glob("*.sql")):
        version = int(path.name.split("_", 1)[0])
        if version in result:
            raise ValueError(f"duplicate migration version {version}")
        result[version] = {"name": path.name, "sha384": hashlib.sha384(path.read_bytes()).hexdigest()}
    return result


def compare(local, upstream):
    return [{"version": version, "local": row["name"], "upstream": upstream[version]["name"]}
        for version, row in local.items() if version in upstream and row["sha384"] != upstream[version]["sha384"]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream-ref")
    parser.add_argument("--applied-json", type=Path, help="JSON array of version/checksum_hex exported from a disposable DB copy")
    args = parser.parse_args()
    local = manifest(Path("migrations"))
    upstream = {}
    if args.upstream_ref:
        # git treats a ref beginning '-' as an option; reject it before invocation.
        if args.upstream_ref.startswith("-"):
            parser.error("invalid upstream ref")
        paths = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", args.upstream_ref, "--", "migrations"], text=True).splitlines()
        for path in paths:
            if not path.endswith(".sql"):
                continue
            raw = subprocess.check_output(["git", "show", f"{args.upstream_ref}:{path}"])
            upstream[int(Path(path).name.split("_", 1)[0])] = {"name": Path(path).name, "sha384": hashlib.sha384(raw).hexdigest()}
    collisions = compare(local, upstream)
    mismatches = []
    if args.applied_json:
        for row in json.loads(args.applied_json.read_text()):
            version = int(row["version"])
            if version not in local or local[version]["sha384"] != row["checksum_hex"]:
                mismatches.append(version)
    print(json.dumps({"schema_version": "soorin.migration-audit.v1", "collisions": collisions,
        "applied_checksum_mismatches": mismatches, "local_count": len(local),
        "safe_to_combine": not collisions and not mismatches}, indent=2, sort_keys=True))
    return int(bool(collisions or mismatches))


if __name__ == "__main__":
    raise SystemExit(main())
