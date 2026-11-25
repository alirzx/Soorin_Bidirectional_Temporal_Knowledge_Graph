"""Exercise the Server 55 preflight with mocked Docker inventory only."""

import json
from types import SimpleNamespace

import unittest
from unittest.mock import patch

from scripts import qualify_production_compose as preflight


class ProductionComposePreflightTests(unittest.TestCase):
    def test_existing_app_data_mount_cannot_be_replaced(self):
        db_target = "/var/lib/postgresql/data"
        app_target = "/app/data"
        data = {"volumes": {"db": {"name": "existing-db"}, "app": {"name": "selected-data"}}}
        services = {
            "db": {"volumes": [{"type": "volume", "source": "db", "target": db_target}]},
            "app": {"volumes": [{"type": "volume", "source": "app", "target": app_target}]},
        }

        def docker(args, **kwargs):
            if args[1] == "volume":
                return SimpleNamespace(stdout="")
            if args[1] == "ps":
                return SimpleNamespace(stdout=args[-1].split("=")[-1] + "\n")
            assert args[1] == "inspect"
            mount = {"Name": "existing-db", "Destination": db_target} if args[-1] == "db" else {
                "Name": "existing-data", "Destination": app_target,
            }
            return SimpleNamespace(stdout=json.dumps([mount]))

        with patch.object(preflight.subprocess, "run", docker):
            with self.assertRaisesRegex(SystemExit, "Existing TKG app has a different volume"):
                preflight.runtime(data, services, False)
            data["volumes"]["app"]["name"] = "existing-data"
            preflight.runtime(data, services, False)
