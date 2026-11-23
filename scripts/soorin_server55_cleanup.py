#!/usr/bin/env python3
"""Inventory historical Server 55 app rollback images. Dry-run by default."""
import argparse
import json
import re
import subprocess

REPO = "soorin-tkg-server55-app"
PROJECT = "soorin-tkg-server55"
ROLLBACK = re.compile(REPO + r":rollback-[0-9]{8}T[0-9]{6}Z\Z")
IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")


def docker(*args):
    result = subprocess.run(["docker", *args], capture_output=True, check=True, text=True, timeout=30)
    return result.stdout.strip()


def inspect(kind, name):
    return json.loads(docker(kind, "inspect", name))[0]


def inventory(rollback):
    if not ROLLBACK.fullmatch(rollback):
        raise ValueError("supply the saved immediate rollback tag from the release record")
    latest = inspect("image", REPO + ":latest")["Id"]
    saved = inspect("image", rollback)["Id"]
    refs, active = {}, []
    for cid in docker("container", "ls", "-aq", "--no-trunc").split():
        c = inspect("container", cid)
        refs.setdefault(c["Image"], []).append(cid)
        labels = c["Config"].get("Labels") or {}
        if (c["State"]["Running"] and labels.get("com.docker.compose.project") == PROJECT and
                labels.get("com.docker.compose.service") == "app"):
            if not any(m.get("Type") == "volume" and m.get("Name") == PROJECT + "_fresh_data_20261123"
                       and m.get("Destination") == "/app/data" for m in c["Mounts"]):
                raise RuntimeError("active app volume mismatch")
            active.append(c["Image"])
    if len(active) != 1 or active[0] != latest:
        raise RuntimeError("running app identity does not match latest release")
    rows = []
    for iid in sorted(set(docker("image", "ls", "--no-trunc", "-q", REPO).split())):
        obj = inspect("image", iid)
        tags = sorted(obj.get("RepoTags") or [])
        older = len(tags) == 1 and ROLLBACK.fullmatch(tags[0]) and tags[0] < rollback
        config = obj.get("Config") or {}
        app_image = ((config.get("Labels") or {}).get("org.opencontainers.image.title") ==
                     "Soorin Bitemporal Knowledge Graph" and config.get("Cmd") == ["utopia-server"])
        removable = bool(app_image and older and iid not in (latest, saved) and not refs.get(iid)
                         and obj["Id"] == iid and IMAGE.fullmatch(iid))
        rows.append({"id": iid, "tags": tags, "bytes": obj["Size"], "containers": refs.get(iid, []),
                     "running": iid == latest, "immediate_rollback": iid == saved, "candidate": removable})
    if any(tag > rollback for row in rows for tag in row["tags"] if ROLLBACK.fullmatch(tag)):
        raise RuntimeError("a newer rollback tag exists; check the immediate release record")
    return rows


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rollback-tag", required=True)
    p.add_argument("--remove-id")
    p.add_argument("--confirmed-tag")
    p.add_argument("--acceptance-passed", action="store_true")
    a = p.parse_args(argv)
    rows = inventory(a.rollback_tag)
    print(json.dumps(rows, indent=2))
    if not a.remove_id:
        return
    if not (IMAGE.fullmatch(a.remove_id) and a.acceptance_passed and a.confirmed_tag):
        p.error("removal requires acceptance, exact sha256 image ID and exact confirmed tag")
    # Repeat all reference and tag checks immediately before one non-forced deletion.
    if not any(r["id"] == a.remove_id and r["tags"] == [a.confirmed_tag] and r["candidate"]
               for r in inventory(a.rollback_tag)):
        p.error("protected, ambiguous or referenced image")
    docker("image", "rm", a.remove_id)


if __name__ == "__main__":
    main()
