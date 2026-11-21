"""Exercise the real HTTP and worker pipeline in an isolated local test instance."""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import time
from uuid import uuid4

from soorin.e2e.local_validation import _request_json
from soorin.e2e.native_validation import bootstrap_synthetic_workspace
from soorin.ontology.importer import OntologyImporter, load_and_validate
from soorin.tests.mock_splunk.scripts.curated_qa_dataset import make_record, PROFILE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--sizes', type=int, nargs='+', choices=(10, 100, 500), default=[10, 100, 500])
    parser.add_argument('--deadline', type=int, default=1200)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if os.getenv('SOORIN_ISOLATED_LOAD') != '1' or args.port < 10000:
        parser.error('requires isolated loopback test port and SOORIN_ISOLATED_LOAD=1')
    base = f'http://127.0.0.1:{args.port}'
    token, ws = bootstrap_synthetic_workspace(base)
    def api(path, body=None, method=None):
        return _request_json(base, path, token=token, body=body,
                             method=method or ('POST' if body is not None else 'GET'))
    ontology = load_and_validate(Path(__file__).parents[1]/'ontology/soc_ontology_v1.yaml')
    reports = []
    for size in args.sizes:
        kb = api(f'/api/v1/workspaces/{ws}/kbs', {'name':f'load-{size}-{uuid4()}', 'visibility':'restricted'})['id']
        root = f'/api/v1/kbs/{kb}'
        OntologyImporter(base, kb, token, request=lambda method,path,body:api(root+path,body,method)).apply(ontology)
        api(root+'/knowledge/binding', {'tenant_id':'tenant-blue','source_system':'splunk','source_instance':'splunk-e2e'}, 'PUT')
        source = api(root+'/sources', {'kind':'statements','name':'load','config':{}})
        path = f"/api/v1/sources/{source['source']['id']}/soc/ingest"
        start = time.monotonic()
        def send(index):
            admitted = _request_json(base, path, method='POST', token=source['ingest_token'],
                                     body={'profile':PROFILE, 'record':make_record(index)})
            return admitted['receipt_id']
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as threads:
            ids = list(threads.map(send, range(size)))
        assert len(set(ids)) == size
        assert send(0) == ids[0]
        report = {'size':size,'kb_id':kb,'accepted':len(ids),'admission_seconds':time.monotonic()-start}
        reports.append(report)
        while True:
            result = api(root+'/knowledge/receipts')
            counts = {row['status']:row['count'] for row in result['counts']}
            report.update(durable=sum(counts.values()),counts=counts,elapsed_seconds=time.monotonic()-start)
            args.report.write_text(json.dumps(reports,indent=2))
            if counts.get('bound') == size:
                report['bound_per_second'] = size/report['elapsed_seconds']
                args.report.write_text(json.dumps(reports,indent=2))
                break
            if report['elapsed_seconds'] > args.deadline or counts.get('quarantined'):
                raise RuntimeError(f'load gate failed for {kb}: {counts}')
            time.sleep(2)
        print(json.dumps(report),flush=True)


if __name__ == '__main__':
    main()
