"""Synthetic normalization -> durable native SOC receipt; no competing queue.

Retries resend the same versioned event. The server persists receipt and job in
one transaction; interruptions can be recovered by replaying the same fixture.
"""
import argparse
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request
import uuid
from soorin.e2e.local_validation import select_isolated_api, normalize_fixture, _load_fixture
from soorin.adapters.utopia import StatementsAdapter


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def submit(base: str, source: str, token: str, event, *, opener=None, attempts=3):
    request = urllib.request.Request(f"{base}/api/v1/sources/{source}/knowledge-events",
        event.to_json().encode(), headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"}, method="POST")
    opener = opener or urllib.request.build_opener(NoRedirect()).open
    for attempt in range(attempts):
        try:
            with opener(request, timeout=30) as response:
                result = json.load(response)
            if result.get("schema_version") != "soorin.ingestion-receipt.v1":
                raise ValueError("invalid receipt schema")
            uuid.UUID(result["receipt_id"])
            if not isinstance(result.get("job_id"), int):
                raise ValueError("invalid receipt job")
            return result
        except urllib.error.HTTPError as exc:
            if exc.code not in {429, 502, 503, 504} or attempt + 1 == attempts:
                raise RuntimeError(f"SOC ingestion rejected: HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError):
            if attempt + 1 == attempts:
                raise RuntimeError("SOC ingestion unavailable after bounded retries") from None
        time.sleep(0.25 * 2 ** attempt)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:2516")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    base = select_isolated_api(args.base_url)
    events = normalize_fixture(_load_fixture(args.fixture))
    source = os.environ.get("UTOPIA_SOURCE_ID", "")
    token = os.environ.get("UTOPIA_INGEST_TOKEN", "")
    if args.execute:
        uuid.UUID(source)
        if not token:
            parser.error("UTOPIA_INGEST_TOKEN is required")
    for scenario, event in events:
        StatementsAdapter().render(event)  # Full local contract/size validation.
        result = submit(base, source, token, event) if args.execute else {"status": "NOT RUN"}
        print(json.dumps({"scenario": scenario, "receipt": result}, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
