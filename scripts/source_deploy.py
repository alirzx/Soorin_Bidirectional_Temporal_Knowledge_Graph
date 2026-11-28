#!/usr/bin/env python3
"""Build and operate the isolated source Compose project without logging its secrets."""
import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
BASE = ["docker-compose.production.yml", "docker-compose.models-isolated.yml", "docker-compose.source.yml"]
ACTIONS = ("config", "preflight", "build-app", "build-models", "status", "images", "up", "health", "stop")


class DeploymentError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise DeploymentError(message)


def command(args, *, env=None, display=False):
    # Compose and database diagnostics can include interpolated secrets.
    result = subprocess.run(args, cwd=ROOT, env=env, text=True, stdout=None if display else subprocess.PIPE,
                            stderr=subprocess.DEVNULL, check=False)
    require(result.returncode == 0, f"{args[0]} operation failed (exit {result.returncode}).")
    return result.stdout


def render(prefix, files, profiles, env):
    cmd = prefix.copy()
    for file in files:
        cmd.extend(["-f", file])
    for profile in profiles:
        cmd.extend(["--profile", profile])
    return cmd, json.loads(command(cmd + ["config", "--format", "json"], env=env))


def configuration(envfile, project, revision):
    require(envfile.is_file(), "Missing operational environment file.")
    env = {**os.environ, "SOORIN_BUILD_REVISION": revision, "COMPOSE_PROFILES": "",
           "COMPOSE_REMOVE_ORPHANS": "0", "COMPOSE_DISABLE_ENV_FILE": "1"}
    prefix = ["docker", "compose", "--project-directory", str(ROOT), "--env-file", str(envfile)]
    if project:
        prefix.extend(["-p", project])
    files, profiles = BASE.copy(), ["models-isolated"]
    cmd, data = render(prefix, files, profiles, env)
    options = data["x-source"]
    require(options["lifecycle"] in ("fresh", "preserve"), "Invalid volume mode.")
    for key in ("soc", "diagnostics", "ner"):
        require(options[key] in ("off", "on"), f"Invalid {key} setting.")
    if options["soc"] == "on":
        files.append("docker-compose.tkg-network.override.yml")
    if options["diagnostics"] == "on":
        files.append("docker-compose.source-diagnostics.yml")
    if options["ner"] == "on":
        files.append("docker-compose.source-ner.yml")
        profiles.append("models-isolated-ner")
    if files != BASE:
        cmd, data = render(prefix, files, profiles, env)
    validate(data)
    return cmd, data, env


def decode_key(key):
    if re.fullmatch(r"[a-fA-F0-9]{64}", key):
        return bytes.fromhex(key)
    return base64.b64decode(key, validate=True)


def validate(data):
    services, options = data["services"], data["x-source"]
    require(re.fullmatch(r"[a-f0-9]{40}", options["model_revision"]), "Use a full model source revision.")
    roles = ["embedding", "reranker"] + (["ner"] if options["ner"] == "on" else [])
    expected = {"db", "app", "models-proxy", *["models-" + role for role in roles]}
    require(set(services) == expected, "Unexpected active services or profile.")
    app, db, proxy = (services[n] for n in ("app", "db", "models-proxy"))
    appnets = {"models", "database", "egress"}
    if options["soc"] == "on":
        appnets.add("aisoc_tkg")
        network = data["networks"]["aisoc_tkg"]
        require(network["name"] == "aisoc-tkg" and network["external"]
                and "soorin-tkg" in app["networks"]["aisoc_tkg"]["aliases"], "Incorrect SOC network.")
    require(set(app["networks"]) == appnets and set(db["networks"]) == {"database"}
            and set(proxy["networks"]) == {"models", "model_roles"}
            and "models" in proxy["networks"]["models"]["aliases"], "Unexpected network topology.")
    require(all(data["networks"][n].get("internal") for n in ("database", "models", "model_roles")),
            "Private networks must be internal.")
    ports = proxy.get("ports", [])
    require(not db.get("ports") and {p["target"] for p in ports} ==
            ({8080, 8081} if options["diagnostics"] == "on" else set()), "Unexpected published ports.")
    require(all(p["host_ip"] in ("127.0.0.1", "::1") for p in ports + app["ports"]), "Loopback binding required.")
    for role in roles:
        worker = services["models-" + role]
        require(set(worker["networks"]) == {"model_roles"} and not worker.get("ports")
                and worker["image"] == services["models-embedding"]["image"]
                and worker["volumes"][0]["read_only"], "Invalid worker isolation.")
    volumes = [v["name"] for v in data["volumes"].values()]
    require(len(volumes) == len(set(volumes)) and all(re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]+", v)
            for v in volumes), "Distinct named volumes required.")
    e, pg = app["environment"], db["environment"]
    require(e["UTOPIA_MODEL_TRUSTED_ORIGINS"].split(",") == [f"http://models:{8080+i}" for i in range(len(roles))],
            "Incorrect trusted model origins.")
    require(pg["POSTGRES_PASSWORD"] != pg["UTOPIA_APP_DB_PASSWORD"], "Database passwords must differ.")
    for variable, user, password in (("UTOPIA_DATABASE_URL", "utopia_app", pg["UTOPIA_APP_DB_PASSWORD"]),
                                     ("UTOPIA_MIGRATION_URL", "utopia", pg["POSTGRES_PASSWORD"])):
        url = urlsplit(e[variable])
        require(url.scheme in ("postgres", "postgresql") and url.hostname == "db" and url.port in (None, 5432)
                and url.path == "/utopia" and url.username == user and unquote(url.password or "") == password
                and not url.query and not url.fragment, "Database role, URL or password mismatch.")
    key = e["UTOPIA_SECRET_KEY"]
    require(len(e["UTOPIA_JWT_SECRET"].encode()) >= 32 and len(decode_key(key)) == 32, "Invalid signing or encryption key.")
    require(urlsplit(e["UTOPIA_CORS_ORIGIN"]).scheme == "https", "HTTPS public origin required.")
    for svc in (db, proxy):
        require(re.fullmatch(r"[^\s]+@sha256:[a-f0-9]{64}", svc["image"]), "Pin DB and proxy images by digest.")
    require(app["image"] != services["models-embedding"]["image"], "Use independent source image tags.")


def containers(*filters):
    args = ["docker", "ps", "-aq"]
    for f in filters:
        args.extend(["--filter", f])
    return command(args).split()


def query(container, user, password, sql):
    return command(["docker", "exec", "-e", "PGPASSWORD", container, "psql", "-XAtw", "-h", "db",
                    "-U", user, "-d", "utopia", "-c", sql], env={**os.environ, "PGPASSWORD": password}).strip()


def check_ledger(container, db_env):
    sql = "SELECT json_agg(json_build_array(version,success,encode(checksum,'hex'))) FROM _sqlx_migrations"
    require(query(container, "utopia_app", db_env["UTOPIA_APP_DB_PASSWORD"], "SELECT current_user") == "utopia_app",
            "Existing runtime role authentication failed.")
    applied = json.loads(query(container, "utopia", db_env["POSTGRES_PASSWORD"], sql))
    manifest = {int(p.name.split("_")[0]): hashlib.sha384(p.read_bytes()).hexdigest()
                for p in (ROOT / "migrations").glob("*.sql")}
    require(applied and all(ok and manifest.get(v) == checksum for v, ok, checksum in applied),
            "Applied migration history is empty, unsuccessful or incompatible.")


def inventory(data):
    services, project, options = data["services"], data["name"], data["x-source"]
    fresh = options["lifecycle"] == "fresh"
    existing = set(command(["docker", "volume", "ls", "--format", "{{.Name}}"]).split())
    volumes = data["volumes"]
    for name, worker in services.items():
        if name.startswith("models-") and name != "models-proxy":
            require(volumes[worker["volumes"][0]["source"]]["name"] in existing, "Provision selected model cache first.")
    if options["soc"] == "on":
        net = json.loads(command(["docker", "network", "inspect", "aisoc-tkg"]))[0]
        require(net["Driver"] == "bridge" and net["Scope"] == "local", "Unexpected SOC network driver or scope.")
    members = containers("label=com.docker.compose.project=" + project)
    records = json.loads(command(["docker", "inspect", *members])) if members else []
    require(not fresh or not records, "Fresh mode requires an unused project.")
    require(all(r["Config"]["Labels"].get("com.docker.compose.service") in services for r in records),
            "Remove or migrate retired project services explicitly before cutover.")
    selected = []
    for name, target, source in (("db", "/var/lib/postgresql/data", "soorin_production_db"),
                                 ("app", "/app/data", "soorin_production_data")):
        volume = volumes[source]["name"]
        selected.append(volume)
        if fresh:
            require(volume not in existing, "Fresh mode requires two new volume names.")
            continue
        match = [r for r in records if r["Config"]["Labels"].get("com.docker.compose.service") == name]
        require(volume in existing and len(match) == 1 and any(m.get("Name") == volume and m["Destination"] == target
                for m in match[0]["Mounts"]), f"Existing {name} volume or project identity mismatch.")
        require(len(containers("volume=" + volume)) == 1, f"Unexpected additional {name} volume consumer.")
        if name == "db":
            db_id = match[0]["Id"]
            check_ledger(db_id, services["db"]["environment"])
        else:
            old = dict(item.split("=", 1) for item in match[0]["Config"]["Env"])
            expected = services["app"]["environment"]
            jwt = old.get("UTOPIA_JWT_SECRET")
            if jwt:
                matches = jwt == expected["UTOPIA_JWT_SECRET"]
            else:
                # Earlier deployments persist the bootstrap signing key in deployment_settings.
                digest = query(db_id, "utopia", services["db"]["environment"]["POSTGRES_PASSWORD"],
                               "SELECT encode(sha256(convert_to(jwt_secret,'UTF8')),'hex') FROM deployment_settings")
                matches = digest == hashlib.sha256(expected["UTOPIA_JWT_SECRET"].encode()).hexdigest()
            require(matches, "Existing JWT signing key differs.")
            key = old.get("UTOPIA_SECRET_KEY")
            if not key:
                key = command(["docker", "exec", match[0]["Id"], "cat", "/app/data/secret.key"]).strip()
            require(decode_key(key) == decode_key(expected["UTOPIA_SECRET_KEY"]), "Existing encryption key differs.")
    return selected if fresh else []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=ACTIONS)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--project")
    args = parser.parse_args()
    revision = command(["git", "rev-parse", "HEAD"]).strip()
    cmd, data, env = configuration(args.env_file.resolve(), args.project, revision)
    def compose(*arguments):
        command(cmd + list(arguments), env=env, display=True)
    action = args.action
    if action == "config":
        print(data["name"], data["x-source"]["lifecycle"], *sorted(data["services"]))
    elif action in ("build-app", "build-models"):
        require(action != "build-models" or data["x-source"]["model_revision"] == revision,
                "Model build must run at the selected model revision.")
        require(not command(["git", "status", "--porcelain"]).strip(), "Build from a clean reviewed checkout.")
        compose("build", "app" if action == "build-app" else "models-embedding")
    elif action in ("up", "preflight"):
        new_volumes = inventory(data)
        if action == "preflight":
            print("Volume, network and lifecycle preflight passed.")
            return
        for name in ("app", "models-embedding", "db", "models-proxy"):
            label = command(["docker", "image", "inspect", "-f", '{{index .Config.Labels "org.opencontainers.image.revision"}}',
                             data["services"][name]["image"]]).strip()
            if name in ("app", "models-embedding"):
                required_revision = revision if name == "app" else data["x-source"]["model_revision"]
                require(label == required_revision, f"{name} image revision differs from selection.")
        # Docker volume create is idempotent. A unique label detects a concurrent creator.
        for volume in new_volumes:
            nonce = uuid.uuid4().hex
            command(["docker", "volume", "create", "--label", "soorin.creation="+nonce, volume])
            actual = command(["docker", "volume", "inspect", "-f", '{{index .Labels "soorin.creation"}}', volume])
            require(actual.strip() == nonce, "Concurrent volume creation detected.")
        compose("up", "-d", "--no-build", "--pull", "never", "--wait")
    elif action == "health":
        roles = ["embedding", "reranker"] + (["ner"] if data["x-source"]["ner"] == "on" else [])
        for port, role in enumerate(roles, start=8080):
            ready = json.loads(command(cmd + ["exec", "-T", "app", "curl", "-fsS", "--max-time", "10",
                                              f"http://models:{port}/ready"], env=env))
            require(ready.get("ready") is True and ready.get("role") == role, f"{role} readiness mismatch.")
        compose("exec", "-T", "app", "curl", "-fsS", "-o", "/dev/null", "http://localhost:1516/api/v1/health")
        print("Application and enabled model endpoints are ready.")
    elif action == "images":
        for image in sorted({s["image"] for s in data["services"].values()}):
            command(["docker", "image", "inspect", "--format",
                     '{{.Id}} {{index .Config.Labels "org.opencontainers.image.revision"}}', image], display=True)
    elif action == "status":
        compose("ps", "-a", "--format", "{{.Service}} {{.Status}}")
    else:
        compose("stop")


if __name__ == "__main__":
    try:
        main()
    except (DeploymentError, OSError, ValueError, KeyError) as error:
        sys.exit(str(error) if isinstance(error, DeploymentError) else "Invalid deployment inputs or unavailable tooling.")
