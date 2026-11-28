"""Synthetic source deployment qualification. No Docker daemon or model weights needed."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import source_deploy as deploy


class SourceDeployment(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.env = Path(temp.name) / "source.env"
        self.settings = {
            "SOORIN_PROD_DB_VOLUME": "fixture-db", "SOORIN_PROD_DATA_VOLUME": "fixture-data",
            "SOORIN_DB_OWNER_PASSWORD": "fixture-owner", "SOORIN_DB_RUNTIME_PASSWORD": "fixture-runtime",
            "SOORIN_RUNTIME_DATABASE_URL": "postgres://utopia_app:fixture-runtime@db:5432/utopia",
            "SOORIN_MIGRATION_DATABASE_URL": "postgres://utopia:fixture-owner@db:5432/utopia",
            "UTOPIA_JWT_SECRET": "synthetic-signing-key-for-ci-only-12345", "UTOPIA_SECRET_KEY": "ab"*32,
            "SOORIN_DB_IMAGE": "example/pg@sha256:"+"a"*64, "SOORIN_MODEL_PROXY_IMAGE": "example/proxy@sha256:"+"b"*64,
        }

    def fixture(self, **overrides):
        template = (deploy.ROOT / ".env.example").read_text()
        values = {**self.settings, **overrides}
        self.env.write_text("\n".join(line.split("=")[0]+"="+values[line.split("=")[0]]
                                      if line.split("=")[0] in values else line for line in template.splitlines()))

    def render(self, project=None, **values):
        self.fixture(**values)
        return deploy.configuration(self.env, project, "a"*40)[1]

    def test_local_default(self):
        data = self.render()
        self.assertEqual(data["name"], "soorin-tkg-local")
        self.assertEqual(set(data["services"]), {"app","db","models-proxy","models-embedding","models-reranker"})
        for role, cpus, memory, capacity in (("embedding", 1.2, 3*1024**3, "2"), ("reranker", 1.4, 3*1024**3, "1")):
            service = data["services"]["models-"+role]
            self.assertEqual(service["image"], "soorin-tkg-cpu:"+"a"*40)
            self.assertEqual(float(service["cpus"]), cpus)
            self.assertEqual(int(service["mem_limit"]), memory)
            self.assertEqual(service["environment"]["SOORIN_MODEL_QUEUE_CAPACITY"], capacity)
            mount = service["volumes"][0]
            self.assertTrue(mount["read_only"])
            self.assertEqual(mount["target"], "/models/"+role)
            self.assertEqual(data["volumes"][mount["source"]]["name"], "soorin-tkg-local_soorin_"+role+"_cache")
        self.assertFalse(data["services"]["models-proxy"].get("ports"))
        self.assertEqual(data["services"]["app"]["environment"]["UTOPIA_MODEL_TRUSTED_ORIGINS"],
                         "http://models:8080,http://models:8081")

    def test_server_options(self):
        data = self.render("soorin-tkg-server55", SOORIN_SOC_INTEGRATION="on", SOORIN_MODEL_DIAGNOSTICS="on",
                           SOORIN_ENABLE_NER="on", SOORIN_VOLUME_MODE="fresh", SOORIN_EMBEDDING_MEMORY="2g")
        self.assertEqual(data["name"], "soorin-tkg-server55")
        self.assertIn("models-ner", data["services"])
        self.assertEqual(set(s for s,v in data["services"].items() if "aisoc_tkg" in v["networks"]), {"app"})
        self.assertEqual(data["networks"]["aisoc_tkg"]["name"], "aisoc-tkg")
        self.assertEqual(int(data["services"]["models-embedding"]["mem_limit"]), 2*1024**3)

    def test_reuse_qualified_model_image(self):
        revision = "b"*40
        data = self.render(SOORIN_MODEL_BUILD_REVISION=revision)
        self.assertEqual(data["x-source"]["model_revision"], revision)
        self.assertEqual(data["services"]["models-reranker"]["image"], "soorin-tkg-cpu:"+revision)
        self.assertEqual(data["services"]["app"]["build"]["args"]["SOORIN_BUILD_REVISION"], "a"*40)

    def test_immutable_runner_remains_compatible(self):
        import os

        self.fixture()
        env = {**os.environ, "SOORIN_PROD_ENV_FILE":str(self.env),
               "SOORIN_IMAGE":"example/app@sha256:"+"c"*64,
               "SOORIN_MODEL_IMAGE":"example/cpu@sha256:"+"d"*64}
        for integrated in ("on", "off"):
            result = subprocess.run(["bash", "scripts/server55_tkg_production.sh", "config"], cwd=deploy.ROOT,
                                    env={**env,"SOORIN_SOC_INTEGRATION":integrated}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("fixture-runtime", result.stdout + result.stderr)

    def test_config_output_and_invalid_inputs(self):
        self.fixture()
        def run():
            return subprocess.run([sys.executable, str(deploy.ROOT/"scripts/source_deploy.py"), "config",
                                   "--env-file", str(self.env)], capture_output=True, text=True)
        ok = run()
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.fixture(SOORIN_PROD_DATA_VOLUME="")
        bad = run()
        self.assertNotEqual(bad.returncode, 0)
        for result in (ok,bad):
            self.assertNotIn("fixture-runtime", result.stdout + result.stderr)
            self.assertNotIn("fixture-owner", result.stdout + result.stderr)

    def test_fresh_and_preserve_inventory(self):
        data = self.render()
        caches = [data["volumes"]["soorin_"+r+"_cache"]["name"] for r in ("embedding","reranker")]
        volumes = caches.copy()
        records = []
        def docker(args, **kwargs):
            if args[1:3] == ["volume","ls"]:
                return "\n".join(volumes)
            if args[1] == "ps":
                return "abc" if args[-1].startswith("volume=") or records else ""
            if args[1] == "inspect":
                return json.dumps(records)
            self.fail("Unexpected Docker operation")
        with patch.object(deploy, "command", side_effect=docker), patch.object(deploy, "check_ledger") as ledger:
            data["x-source"]["lifecycle"] = "fresh"
            self.assertEqual(deploy.inventory(data), ["fixture-db","fixture-data"])
            volumes.append("fixture-db")
            with self.assertRaises(deploy.DeploymentError):
                deploy.inventory(data)
            data["x-source"]["lifecycle"] = "preserve"
            volumes.append("fixture-data")
            with self.assertRaises(deploy.DeploymentError):
                deploy.inventory(data)
            for service, volume, target in (("app","fixture-data","/app/data"),("db","fixture-db","/var/lib/postgresql/data")):
                records.append({"Id":service,"Mounts":[{"Name":volume,"Destination":target}],
                                "Config":{"Labels":{"com.docker.compose.service":service},
                                          "Env":[k+"="+v for k,v in self.settings.items()]}})
            self.assertEqual(deploy.inventory(data), [])
            ledger.assert_called_once()
            records[0]["Mounts"][0]["Name"] = "different-data"
            with self.assertRaises(deploy.DeploymentError):
                deploy.inventory(data)

    def test_preserve_checks_applied_checksums(self):
        env = {"UTOPIA_APP_DB_PASSWORD":"test", "POSTGRES_PASSWORD":"owner"}
        for invalid in ([], [[10009, True, "wrong"]], [[999999, True, "unknown"]], [[10009, False, "failed"]]):
            with patch.object(deploy, "query", side_effect=["utopia_app",json.dumps(invalid)]):
                with self.assertRaises(deploy.DeploymentError):
                    deploy.check_ledger("db", env)

    def test_build_commands_only_build(self):
        self.fixture()
        for action, service in (("build-models","models-embedding"),("build-app","app")):
            real = deploy.command
            writes = []
            def dispatch(args, **kwargs):
                if args[:2] == ["git","status"]:
                    return ""
                if kwargs.get("display"):
                    writes.append(args[-2:])
                    return ""
                return real(args, **kwargs)
            with patch.object(sys,"argv",["runner",action,"--env-file",str(self.env)]), patch.object(deploy,"command",dispatch):
                deploy.main()
            self.assertEqual(writes, [["build",service]])
