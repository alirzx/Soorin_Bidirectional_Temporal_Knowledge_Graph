"""Provider-independent native SOC client. No model or Agentic_SOC dependencies."""
from __future__ import annotations
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from uuid import UUID
from soorin.contracts import SecurityKnowledgeEvent


class KnowledgeClientError(RuntimeError):
    def __init__(self, code: str, status: int | None = None, retryable: bool = False):
        self.code, self.status, self.retryable = code, status, retryable
        super().__init__(code)  # Never include tokens, event bytes or server bodies.


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class KnowledgeClient:
    def __init__(self, base_url: str, *, source_token: str = '', session_token: str = '',
                 timeout: float = 10, retries: int = 2, transport=None, sleep=time.sleep):
        parsed = urllib.parse.urlsplit(base_url)
        if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment or parsed.path not in {'', '/'}):
            raise ValueError('invalid_api_origin')
        if parsed.scheme != 'https' and parsed.hostname not in {'localhost', '127.0.0.1', '::1'}:
            raise ValueError('https_required')
        if not 0 < timeout <= 30 or not 0 <= retries <= 3:
            raise ValueError('invalid_retry_budget')
        self.base = base_url.rstrip('/')
        self.source_token, self.session_token = source_token, session_token
        self.timeout, self.retries, self.sleep = timeout, retries, sleep
        self.transport = transport or self._transport

    def _transport(self, method, url, headers, body):
        request = urllib.request.Request(url, method=method, headers=headers, data=body)
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=self.timeout) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
                if len(raw) > 2 * 1024 * 1024:
                    raise KnowledgeClientError('response_too_large')
                return response.status, json.loads(raw)
        except urllib.error.HTTPError as exc:
            return exc.code, {}  # Discard error bodies.
        except (urllib.error.URLError, TimeoutError, OSError):
            raise KnowledgeClientError('transport_unavailable', retryable=True) from None
        except ValueError:
            raise KnowledgeClientError('invalid_json_response') from None

    def _request(self, path, payload, token, schema):
        if not token:
            raise KnowledgeClientError('credential_required')
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
        headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json', 'Accept': 'application/json'}
        for attempt in range(self.retries + 1):
            try:
                status, result = self.transport('POST', self.base + '/api/v1' + path, headers, body)
                if not 200 <= status < 300:
                    raise KnowledgeClientError('api_rejected', status, status in {408, 429, 500, 502, 503, 504})
                if not isinstance(result, dict) or result.get('schema_version') != schema:
                    raise KnowledgeClientError('response_schema_mismatch')
                return result
            except KnowledgeClientError as exc:
                if not exc.retryable or attempt == self.retries:
                    raise
                self.sleep(min(2 ** attempt, 4))
        raise AssertionError('unreachable')

    def ingest(self, source_id: str, event: SecurityKnowledgeEvent):
        # The same canonical event bytes/checksum are retried, never regenerated.
        from soorin.contracts.native_profile import validate_native_event
        validate_native_event(event)
        return self._request('/sources/' + str(UUID(source_id)) + '/knowledge-events', event.to_dict(),
                             self.source_token, 'soorin.ingestion-receipt.v1')

    def context(self, kb_id: str, *, tenant_id: str, entity: str, at=None, as_of=None, limit=40):
        if not tenant_id or not entity or not 1 <= limit <= 100:
            raise ValueError('invalid_context_query')
        payload = {'tenant_id': tenant_id, 'entity': entity, 'limit': limit}
        if at is not None:
            payload['at'] = at
        if as_of is not None:
            UUID(entity)  # Historical lookup cannot use today's aliases.
            payload['as_of'] = as_of
        return self._request('/kbs/' + str(UUID(kb_id)) + '/knowledge/context', payload,
                             self.session_token, 'soorin.knowledge-context.v2')
