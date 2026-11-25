#!/usr/bin/env python3
"""Validate hardened TKG Compose without exposing interpolated configuration."""

import argparse
import json
import re
import subprocess
import sys
from urllib.parse import urlsplit


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def config(data, integrated):
    services = data["services"]
    require(set(services) == {"db", "app", "models"}, "Expected one unified production model service")
    app, db, models = (services[name] for name in ("app", "db", "models"))
    for name, service in services.items():
        require(re.fullmatch(r"[^\s]+@sha256:[a-f0-9]{64}", service.get("image", "")), f"{name}: qualified image digest required")
        require(service.get("cpus") and service.get("mem_limit") and service.get("healthcheck"), f"{name}: resource or health limits missing")
        require(not service.get("build"), f"{name}: production images must be qualified separately")
    require(app.get("read_only") and models.get("read_only") and app.get("user") == models.get("user") == "65532:65532",
            "App and models must run read-only as the approved non-root user")
    require(set(db["networks"]) == {"database"} and set(models["networks"]) == {"models"}, "DB and model networks must remain private")
    require(all(data["networks"][name]["internal"] for name in ("database", "models")), "Private model/database network is not internal")
    require(not db.get("ports") and not models.get("ports"), "DB and models must not publish ports")
    require(set(app["networks"]) == ({"database", "models", "egress", "aisoc_tkg"} if integrated else {"database", "models", "egress"}),
            "Unexpected app network membership")
    if integrated:
        network = data["networks"]["aisoc_tkg"]
        require(network.get("external") and network["name"] == "aisoc-tkg", "Expected the separate aisoc-tkg network")
        require("soorin-tkg" in app["networks"]["aisoc_tkg"]["aliases"], "Missing private SOC alias")
    require(all(port.get("host_ip") in {"127.0.0.1", "::1"} and port["target"] == 1516 for port in app.get("ports", [])),
            "Hardened app publication must use a loopback HTTPS proxy")
    env = app["environment"]
    require(env.get("UTOPIA_BIND_ADDR") == "0.0.0.0:1516" and env.get("UTOPIA_MODEL_TEST_MODE") == "0",
            "Wrong TKG listener or model-test mode")
    runtime, owner = (urlsplit(env[name]) for name in ("UTOPIA_DATABASE_URL", "UTOPIA_MIGRATION_URL"))
    require(runtime.username == "utopia_app" and owner.username == db["environment"]["POSTGRES_USER"]
            and runtime.username != owner.username, "Verify separate application and migration database roles")
    require(runtime.hostname == owner.hostname == "db" and runtime.path == owner.path == "/utopia",
            "Database URLs must reference the expected local database")
    require(models.get("profiles") == ["models"] and all(mount["read_only"] for mount in models.get("volumes", [])),
            "Unified models require offline read-only caches")
    return services


def runtime(data, services, integrated):
    if integrated:
        subprocess.run(["docker", "network", "inspect", "aisoc-tkg"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for service in services.values():
        for mount in service.get("volumes", []):
            if mount["type"] == "volume":
                volume = data["volumes"][mount["source"]]["name"]
                subprocess.run(["docker", "volume", "inspect", volume], check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for name, target in (("db", "/var/lib/postgresql/data"), ("app", "/app/data")):
        planned = next(m for m in services[name]["volumes"] if m["target"] == target)
        expected = data["volumes"][planned["source"]]["name"]
        containers = subprocess.run(
            ["docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=soorin-tkg-server55",
             "--filter", f"label=com.docker.compose.service={name}"],
            check=True, capture_output=True, text=True,
        ).stdout.split()
        for container in containers:
            mounts = subprocess.run(["docker", "inspect", "--format", "{{json .Mounts}}", container],
                                    check=True, capture_output=True, text=True)
            require(any(m.get("Name") == expected and m["Destination"] == target for m in json.loads(mounts.stdout)),
                    f"Existing TKG {name} has a different volume. Review the cutover plan before proceeding.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("integration", choices=("off", "on"))
    parser.add_argument("--runtime", action="store_true")
    args = parser.parse_args()
    try:
        data = json.load(sys.stdin)
        services = config(data, args.integration == "on")
        if args.runtime:
            runtime(data, services, args.integration == "on")
    except (KeyError, ValueError, subprocess.SubprocessError):
        raise SystemExit("TKG configuration or preflight failed. Verify required settings and existing resources locally.") from None
    print("PASS: hardened TKG production configuration validated. No resolved settings printed.")


if __name__ == "__main__":
    main()
