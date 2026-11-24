import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from uuid import uuid4

from scripts import soorin_server55_cleanup as cleanup
from soorin.e2e import soc_production_reliability as suite
from soorin.e2e import reliability_5k_http as http
from soorin.ops.http_adapter import normalize


def http_error(code, msg="unavailable"):
    return HTTPError("http://localhost", code, "", {}, io.BytesIO(json.dumps({"error": msg}).encode()))


class ProductionAcceptance(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.out = Path(temp.name) / "run"
        self.kb, self.source = str(uuid4()), str(uuid4())
        self.args = ["--out", str(self.out), "--kb-id", self.kb, "--source-id", self.source,
                     "--count", "2", "--rps", "100", "--deadline", "3"]
        suite.main(["prepare", *self.args])
        self.manifest = suite.read(self.out, "manifest")
        self.env = patch.dict(os.environ, {"SESSION_TOKEN": "session-secret", "INGEST_TOKEN": "source-secret",
                              "SCOPED_READ_TOKEN": "read-secret", "OTHER_KB_ID": str(uuid4())})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_offline_report_and_deterministic_contract(self):
        self.assertEqual(suite.report(self.out), "NOT_TESTED")
        self.assertEqual(self.manifest["scope"]["source"], self.source)
        rows = http.load_payloads(self.out, False)
        preview = normalize(dict(**json.loads(rows[0][1]), tenant_id="tenant-blue",
                                 source_instance="splunk-e2e", source_system="splunk"))
        self.assertEqual(preview["canonical_event"]["source_record_id"], "soc-alert-synthetic-00000")
        self.assertFalse(preview["persistent_writes"])
        alert = next(e for e in preview["canonical_event"]["entities"] if e["entity_type"] == "SecurityAlert")
        self.assertEqual(alert["source_identifiers"], {"soc_alert_row_id": "soc-alert-synthetic-00000"})
        with self.assertRaises(RuntimeError):
            suite.main(["prepare", *self.args])

    def test_guard_rejects_target_change_before_http(self):
        with patch.object(http, "_json", side_effect=AssertionError):
            with self.assertRaisesRegex(ValueError, "target mismatch"):
                suite.main(["send", *self.args, "--target-profile", "server"])
        with patch.object(http, "verify_server_target", side_effect=AssertionError):
            from types import SimpleNamespace
            with self.assertRaisesRegex(ValueError, "allow-existing"):
                suite.profile(SimpleNamespace(target_profile="server", allow_existing_server=False))

    def test_published_connector_request_and_ranking_fixture(self):
        import re
        from soorin.evaluation.retrieval_benchmark import quality_at_cutoffs
        path = Path(__file__).resolve().parents[2] / "docs/soorin/AGENTIC_SOC_INTEGRATION_V1.md"
        blocks = re.findall(r"```json\n(.*?)\n```", path.read_text().split("## Connector REST contract")[1], re.S)
        wire = [json.loads(b) for b in blocks]
        response = normalize(dict(**wire[0], tenant_id="tenant-blue", source_system="splunk", source_instance="splunk-e2e"))
        for key, value in wire[1]["canonical_event"].items():
            self.assertEqual(response["canonical_event"][key], value)
        self.assertEqual(wire[8]["authority_name"], "soc_alert_row_id")
        self.assertEqual(set(quality_at_cutoffs()["dense_only_mock"]), {"mrr10", "recall5", "recall10", "ndcg10"})

    def test_transient_conflicts_timeouts_and_retry_exhaustion(self):
        ack = {"receipt_id": str(uuid4()), "schema_version": "soorin.ingestion-receipt.v1", "replayed": True}
        cases = [
            ([http_error(429), http_error(503), TimeoutError(), ack], "accepted", 4),
            ([http_error(409, "soc_normalizer_busy"), ack], "accepted", 2),
            ([http_error(409, "synthetic_record_range_occupied")], "http_409", 1),
            ([http_error(422)], "http_422", 1),
            ([http_error(503) for _ in range(4)], "http_503", 4),
            ([{"receipt_id": "invalid"}], "invalid_response", 1),
            ([{}], "invalid_ack", 1),
        ]
        for responses, outcome, count in cases:
            with self.subTest(outcome=outcome), patch.object(http, "_json", side_effect=responses), patch.object(http.time, "sleep"):
                row = http.send_one("r", b"{}", "http://localhost", "secret", 4, http.RateLimit(0), "run")
                self.assertEqual((row["outcome"], len(row["history"])), (outcome, count))
                self.assertNotIn("secret", json.dumps(row))

    def test_duplicate_and_empty_graph_are_failures(self):
        rid = str(uuid4())
        with (self.out / "accepted.jsonl").open("w") as f:
            for i in range(2):
                f.write(json.dumps(dict(receipt_id=rid, run_id=self.manifest["run_id"], item=f"alerts.jsonl:{i}", history=["accepted"],
                                        attempt=1, latency_seconds=.1)) + "\n")
        r = suite.admission_report(self.out, .2)
        self.assertEqual((r["status"], r["duplicate_acknowledgments"]), ("FAIL", 1))
        self.assertFalse(suite.graph_ok({}, self.manifest, rid))

    def test_full_guarded_flow_with_delayed_binding_and_vector_recovery(self):
        ids, docs, polls = {}, {}, []
        scope = {k: self.manifest["scope"][k] for k in ("tenant_id","source_system","source_instance")}
        def remote(url, token, *, payload=None, run_id=None, **kwargs):
            if url.endswith("/sources"):
                return {"sources": [{"kind": "statements", "id": self.source}]}
            if url.endswith("/preview"):
                return {"canonical_event": scope, "supports_acceptance_run": True, "persistent_writes": False}
            if url.endswith("/ingest"):
                self.assertEqual(run_id, self.manifest["run_id"])
                index = json.loads(payload)["record"]["alert_row_id"]
                rid = ids.setdefault(index, str(uuid4()))
                docs[rid] = str(uuid4())
                return {"schema_version":"soorin.ingestion-receipt.v1","receipt_id": rid, "replayed": False}
            if "receipts?limit" in url:
                polls.append(1)
                return {"receipts":[{"receipt_id": rid, "source_id": self.source,
                        "status": "submitted" if len(polls)==1 else "bound", "delivery_state":"bound",
                        "created_at":"2026-01-01T00:00:00Z", "updated_at":"2026-01-01T00:00:02Z"}
                        for rid in docs]}
            if "/receipts/" in url:
                if token == "read-secret":
                    raise http_error(403)
                rid = url.rsplit("/",1)[1]
                return {"receipt_id":rid, "source_id":self.source, "source_scope":scope, "status":"bound",
                        "document":{"document_id":docs[rid],"document_version":1,"status":"ready","graph_status":"done"},
                        "unsupported_relation_count":0,"evidence_view":"current_document_version",
                        "entities":[{"type_matches":True,"authority_linked":True,"entity_id":str(uuid4())}],
                        "relations":[{"binding":{"evidence_link_status":True}}]}
            b = json.loads(payload)
            if os.environ["OTHER_KB_ID"] in url or b.get("tenant_id","").startswith("mismatch"):
                raise http_error(404)
            if url.endswith("/resolve"):
                self.assertEqual(b["authority_name"], "soc_alert_row_id")
                return {"status":"resolved", "knowledge_base_id":self.kb,"candidates":[{"entity_id":str(uuid4())}]}
            if url.endswith("/context"):
                return {"knowledge_base_id":self.kb,"tenant_id":"tenant-blue","facts":[{}],"evidence_references":[{}]}
            past = "as_of" in b
            return {"results":[] if past else [{"document_id":d,"text":b["q"]} for d in docs.values()],
                    "retrieval":{"lexical_method":"postgres_versioned_lexical" if past else "tantivy_bm25",
                                 "dense_executed":True,"reranker_status":"complete"}}
        coverage = [{"status":"FAIL","missing":1},{"status":"PASS","missing":0}]
        with patch.object(http,"_json",side_effect=remote), patch.object(suite,"profile"), \
             patch.object(http,"_docker_inspect",return_value={"Id":"container","Image":"image","Config":{}}), \
             patch.object(suite,"db",return_value=0), patch.object(suite,"snapshot",return_value={"deployment":{},"image_id":"image","revision":None}), \
             patch.object(suite,"coverage",side_effect=coverage), patch.object(suite.time,"sleep"):
            for mode in ("preflight", "send", "verify"):
                suite.main([mode, *self.args])
            self.assertEqual(suite.report(self.out), "PASS")
            self.assertTrue(all(p["status"] == "PASS" for p in suite.read(self.out, "verification-phases").values()))
            self.assertEqual(suite.read(self.out,"job-metrics")["polls_observing_state"]["submitted"],1)
            manifest_path = self.out / "manifest.json"
            original = manifest_path.read_text()
            manifest_path.write_text(original + "\n")
            self.assertEqual(suite.report(self.out), "INCONCLUSIVE")
            manifest_path.write_text(original)
            self.assertEqual(suite.report(self.out), "PASS")
            with patch.object(http, "_docker_inspect", return_value={"Id":"replacement","Image":"new","Config":{}}):
                with self.assertRaisesRegex(ValueError, "deployed target changed"):
                    suite.main(["send", *self.args])
            self.assertEqual(suite.report(self.out), "INCONCLUSIVE")
            with patch.object(suite,"db",return_value=1), self.assertRaisesRegex(ValueError,"occupied"):
                suite.main(["preflight",*self.args])
        self.assertEqual(suite.read(self.out,"job-metrics")["bound_latency_seconds"]["p95"], 2)
        for file in self.out.glob("*json*"):
            self.assertNotIn("session-secret", file.read_text())

    def test_phase_records_timeout_and_interruption(self):
        from contextlib import redirect_stdout
        phases = {name: {"status": "NOT_TESTED"} for name in suite.PHASES}
        with redirect_stdout(io.StringIO()) as output:
            for error, status in [(TimeoutError(), "deadline"), (KeyboardInterrupt(), "interrupted")]:
                with self.subTest(status=status), self.assertRaises(type(error)):
                    with suite.phase(self.out, phases, "receipts", 30):
                        raise error
                data = suite.read(self.out, "verification-phases")
                self.assertEqual(data["receipts"]["status"], "INCONCLUSIVE")
                self.assertEqual(data["receipts"]["reason"], status)
                self.assertEqual(data["graph"]["status"], "NOT_TESTED")
                self.assertEqual(suite.report(self.out), "INCONCLUSIVE")
            self.assertIn('"elapsed_seconds"', output.getvalue())

    def test_search_timeout_obeys_remaining_phase_budget(self):
        from types import SimpleNamespace
        a = SimpleNamespace(base_url=http.DEFAULT_BASE, kb_id=self.kb, probe_timeout=80)
        with patch.object(http, "_json", side_effect=TimeoutError) as request:
            result = suite.probe(a, "synthetic", until=suite.time.monotonic() + 2)
        self.assertEqual(result["error"], "timeout")
        self.assertGreater(request.call_args.kwargs["timeout"], 0)
        self.assertLessEqual(request.call_args.kwargs["timeout"], 2)

    def test_skipped_security_prevents_pass(self):
        with patch.dict(os.environ, clear=True):
            a = type("Target", (), {"kb_id": self.kb})()
            self.assertEqual(suite.isolation(a, self.manifest, "unused"), "NOT_TESTED")

    def test_coverage_rejects_wrong_identity_missing_docs_and_partial_vectors(self):
        for model, docs, active, embedded, incompatible, status in [
            (suite.MODEL, 2, 3, 3, 0, "PASS"),
            ("old", 2, 3, 3, 0, "FAIL"),
            (suite.MODEL, 1, 1, 1, 0, "FAIL"),
            (suite.MODEL, 2, 3, 2, 1, "FAIL"),
            (suite.MODEL, 0, 0, 0, 0, "FAIL"),
        ]:
            rows = [["http://models:8080/v1", model, 1024],
                    {"documents_with_chunks":docs,"active":active,"embedded":embedded,"incompatible":incompatible}]
            with self.subTest(rows=rows), patch.object(suite, "db", side_effect=rows):
                self.assertEqual(suite.coverage("db", self.manifest)["status"], status)

    def test_failed_reranker_is_visible_even_with_results(self):
        for status in ("fallback", "complete"):
            with patch.object(http, "_json", return_value={"retrieval": {"dense_executed":True,
                "lexical_method":"tantivy_bm25","reranker_status":status}, "results":[]}):
                from types import SimpleNamespace
                p = suite.probe(SimpleNamespace(base_url=http.DEFAULT_BASE,kb_id=self.kb),"id")
                self.assertTrue(p["ok"])
                self.assertEqual(p["reranker"], status)

    def test_dry_run_cleanup_protects_referenced_and_multitagged_ids(self):
        ids = ["sha256:" + str(i)*64 for i in range(1,6)]
        tags = [cleanup.REPO + ":latest"] + [cleanup.REPO + f":rollback-2026110{i}T000000Z" for i in (8,1,2,3)]
        images = {iid: {"Id":iid,"RepoTags":[tag],"Size":100,
                        "Config":{"Labels":{"org.opencontainers.image.title":"Soorin Bitemporal Knowledge Graph"},
                                  "Cmd":["utopia-server"]}} for iid,tag in zip(ids,tags)}
        images[ids[4]]["RepoTags"].append("unrelated:latest")
        def inspect(kind, name):
            if kind == "image":
                return images[name if name in images else ids[tags.index(name)]]
            return {"Image": ids[0] if name=="app" else ids[3], "Config":{"Labels":{
                "com.docker.compose.project":cleanup.PROJECT,"com.docker.compose.service":"app"}},
                "State":{"Running":name=="app"}, "Mounts":[{"Type":"volume","Name":suite.APP_VOLUME,"Destination":"/app/data"}]}
        def docker(*args):
            self.assertNotIn("rm", args)
            return "app stopped" if args[0]=="container" else " ".join(ids)
        with patch.object(cleanup,"inspect",side_effect=inspect), patch.object(cleanup,"docker",side_effect=docker):
            rows = cleanup.inventory(tags[1])
            self.assertEqual([r["id"] for r in rows if r["candidate"]], [ids[2]])
            cleanup.main(["--rollback-tag", tags[1]])
