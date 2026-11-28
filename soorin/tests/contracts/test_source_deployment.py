"""Synthetic source deployment qualification. No Docker daemon or model weights needed."""
from contextlib import redirect_stdout
import io
import json
import os
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

    def test_server55_lan_preserves_topology_and_volumes(self):
        project = "soorin-tkg-server55"
        db_volume = project + "_fresh_db_20261128"
        data_volume = project + "_fresh_data_20261128"
        settings = {
            "SOORIN_ACCESS_MODE": "lan-http", "SOORIN_APP_BIND": "192.168.0.55:2516",
            "SOORIN_PUBLIC_ORIGIN": "http://192.168.0.55:2516",
            "SOORIN_PROD_DB_VOLUME": db_volume, "SOORIN_PROD_DATA_VOLUME": data_volume,
        }
        data = self.render(project, **settings)
        self.assertEqual(data["x-source"]["lifecycle"], "preserve")
        services = data["services"]
        self.assertEqual(set(services), {"db", "app", "models-embedding", "models-reranker", "models-proxy"})
        self.assertNotIn("aisoc_tkg", data["networks"])
        enabled = self.render(project, SOORIN_SOC_INTEGRATION="on", **settings)["services"]
        self.assertEqual(set(s for s, v in enabled.items() if "aisoc_tkg" in v["networks"]), {"app"})
        self.assertIn("soorin-tkg", enabled["app"]["networks"]["aisoc_tkg"]["aliases"])
        self.assertTrue(all(not service.get("ports") for name, service in services.items() if name != "app"))
        app = services["app"]
        binding, = app["ports"]
        self.assertEqual((binding["host_ip"], str(binding["published"]), binding["target"]),
                         ("192.168.0.55", "2516", 1516))
        self.assertEqual(app["environment"]["UTOPIA_CORS_ORIGIN"], "http://192.168.0.55:2516")
        self.assertEqual(app["environment"]["UTOPIA_COOKIE_SECURE"], "false")
        self.assertEqual(app["environment"]["UTOPIA_OPEN_REGISTRATION"], "false")
        self.assertEqual(app["environment"]["UTOPIA_MODEL_TRUSTED_ORIGINS"], "http://models:8080,http://models:8081")
        for name, expected in (("db", db_volume), ("app", data_volume),
                               ("models-embedding", project + "_soorin_embedding_cache"),
                               ("models-reranker", project + "_soorin_reranker_cache")):
            mount = services[name]["volumes"][0]
            self.assertEqual(data["volumes"][mount["source"]]["name"], expected)

    def test_lan_loopback_bootstrap_and_existing_https_default(self):
        lan = self.render(SOORIN_ACCESS_MODE="lan-http", SOORIN_PUBLIC_ORIGIN="http://localhost:2516",
                          SOORIN_VOLUME_MODE="fresh")
        self.assertEqual(lan["services"]["app"]["environment"]["UTOPIA_COOKIE_SECURE"], "false")
        tls = self.render()
        self.assertEqual(tls["services"]["app"]["environment"]["UTOPIA_COOKIE_SECURE"], "true")

    def test_reject_accidental_public_http_and_mismatched_origin(self):
        invalid = [
            ("https-proxy", "127.0.0.1:2516", "http://127.0.0.1:2516"),
            ("https-proxy", "192.168.0.55:2516", "https://example.test"),
            ("lan-http", "0.0.0.0:2516", "http://0.0.0.0:2516"),
            ("lan-http", "169.254.4.2:2516", "http://169.254.4.2:2516"),
            ("lan-http", "198.51.100.2:2516", "http://198.51.100.2:2516"),
            ("lan-http", "192.168.0.55:2516", "http://192.168.0.56:2516"),
            ("lan-http", "192.168.0.55:2516", "http://192.168.0.55"),
            ("lan-http", "192.168.0.55:2516", "https://192.168.0.55:2516"),
            ("lan-http", "192.168.0.55:2516", "http://192.168.0.55:2516/app"),
            ("lan-http", "192.168.0.55:2516", "http://fixture:secret@192.168.0.55:2516"),
            ("http", "127.0.0.1:2516", "http://127.0.0.1:2516"),
        ]
        for mode, bind, origin in invalid:
            with self.subTest(mode=mode, bind=bind, origin=origin):
                with self.assertRaises(deploy.DeploymentError):
                    self.render(SOORIN_ACCESS_MODE=mode, SOORIN_APP_BIND=bind, SOORIN_PUBLIC_ORIGIN=origin)

    def test_inspect_optional_labels_and_required_provenance(self):
        data = self.render(SOORIN_MODEL_BUILD_REVISION="b"*40)
        services = data["services"]
        records = {}
        for name, revision in (("app", "a"*40), ("models-embedding", "b"*40)):
            records[services[name]["image"]] = {"Id": "fixture-" + name,
                "Config": {"Labels": {"org.opencontainers.image.revision": revision}}}
        for name, config in (("db", {}), ("models-proxy", {"Labels": None})):
            reference = services[name]["image"]
            records[reference] = {"Id": "fixture-" + name, "Config": config, "RepoDigests": [reference]}

        def inspect(args):
            try:
                return json.dumps([records[args[-1]]])
            except KeyError:
                raise deploy.DeploymentError("image missing") from None

        with patch.object(deploy, "command", side_effect=inspect):
            output = io.StringIO()
            with redirect_stdout(output):
                deploy.inspect_images(data, "a"*40, display=True)
            self.assertIn("db fixture-db third-party digest", output.getvalue())
            self.assertIn("models-embedding fixture-models-embedding source revision " + "b"*40, output.getvalue())
            model = records[services["models-embedding"]["image"]]
            with patch.dict(model["Config"], {"Labels": None}):
                with self.assertRaisesRegex(deploy.DeploymentError, "image revision differs"):
                    deploy.inspect_images(data, "a"*40)
            with self.assertRaisesRegex(deploy.DeploymentError, "image revision differs"):
                deploy.inspect_images(data, "c"*40)
            db = records[services["db"]["image"]]
            with patch.dict(db, {"RepoDigests": []}):
                with self.assertRaisesRegex(deploy.DeploymentError, "selected registry digest"):
                    deploy.inspect_images(data, "a"*40)
            del records[services["db"]["image"]]
            with self.assertRaises(deploy.DeploymentError):
                deploy.inspect_images(data, "a"*40)

    def test_reuse_qualified_model_image(self):
        revision = "b"*40
        data = self.render(SOORIN_MODEL_BUILD_REVISION=revision)
        self.assertEqual(data["x-source"]["model_revision"], revision)
        self.assertEqual(data["services"]["models-reranker"]["image"], "soorin-tkg-cpu:"+revision)
        self.assertEqual(data["services"]["app"]["build"]["args"]["SOORIN_BUILD_REVISION"], "a"*40)

    def test_immutable_runner_remains_compatible(self):
        self.fixture()
        env = {**os.environ, "SOORIN_PROD_ENV_FILE":str(self.env),
               "SOORIN_IMAGE":"example/app@sha256:"+"c"*64,
               "SOORIN_MODEL_IMAGE":"example/cpu@sha256:"+"d"*64}
        for integrated in ("on", "off"):
            result = subprocess.run(["bash", "scripts/server55_tkg_production.sh", "config"], cwd=deploy.ROOT,
                                    env={**env,"SOORIN_SOC_INTEGRATION":integrated}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("fixture-runtime", result.stdout + result.stderr)
        bad = subprocess.run(["bash", "scripts/server55_tkg_production.sh", "config"], cwd=deploy.ROOT,
                             env={**env, "SOORIN_PUBLIC_ORIGIN": "http://localhost:2516"}, capture_output=True, text=True)
        self.assertNotEqual(bad.returncode, 0)

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
            app = data["services"]["app"]
            data["x-source"]["access"] = "lan-http"
            app["ports"][0]["host_ip"] = "192.168.0.55"
            with patch.object(deploy, "query", return_value="f"):
                with self.assertRaisesRegex(deploy.DeploymentError, "close registration"):
                    deploy.inventory(data)
            with patch.object(deploy, "query", return_value="t"):
                self.assertEqual(deploy.inventory(data), [])
            data["x-source"]["lifecycle"] = "fresh"
            with self.assertRaisesRegex(deploy.DeploymentError, "loopback"):
                deploy.inventory(data)
            data["x-source"]["lifecycle"] = "preserve"
            data["x-source"]["access"] = "https-proxy"
            records[0]["Mounts"][0]["Name"] = "different-data"
            with self.assertRaises(deploy.DeploymentError):
                deploy.inventory(data)

    def test_preserve_checks_applied_checksums(self):
        env = {"UTOPIA_APP_DB_PASSWORD":"test", "POSTGRES_PASSWORD":"owner"}
        for invalid in ([], [[10009, True, "wrong"]], [[999999, True, "unknown"]], [[10009, False, "failed"]]):
            with patch.object(deploy, "query", side_effect=["utopia_app",json.dumps(invalid)]):
                with self.assertRaises(deploy.DeploymentError):
                    deploy.check_ledger("db", env)

    def test_up_app_only_keeps_dependencies_and_checks_images(self):
        self.fixture()
        real = deploy.command
        with patch.object(sys, "argv", ["runner", "up", "--app-only", "--env-file", str(self.env)]), \
                patch.object(deploy, "inventory", return_value=[]) as inventory, \
                patch.object(deploy, "inspect_images") as images, \
                patch.object(deploy, "command", wraps=deploy.command) as shell:
            # Mock the final Compose action while allowing actual config rendering above.
            shell.side_effect = lambda args, **kwargs: None if kwargs.get("display") else real(args, **kwargs)
            deploy.main()
            inventory.assert_called_once()
            images.assert_called_once()
            self.assertEqual(shell.call_args.args[0][-8:],
                             ["up", "-d", "--no-build", "--pull", "never", "--wait", "--no-deps", "app"])

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
