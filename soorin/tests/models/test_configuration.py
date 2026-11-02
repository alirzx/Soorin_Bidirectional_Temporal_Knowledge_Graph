from __future__ import annotations

import unittest
from io import BytesIO
from unittest.mock import patch
import urllib.error

from soorin.models import OpenAIChatHealthClient, OpenAIEmbeddingClient
from soorin.models.configuration import ChatConfig, ConfigurationError, EmbeddingConfig, RerankerConfig, SoorinModelConfig
from soorin.models.openai_compatible import ProviderError, _http_json


class ConfigurationTests(unittest.TestCase):
    def test_disabled_defaults_start_without_models(self):
        config = SoorinModelConfig.from_env({})
        self.assertFalse(config.chat.enabled)
        self.assertFalse(config.embedding.enabled)
        self.assertFalse(config.reranker.enabled)

    def test_workspace_overrides_environment_and_keys_are_redacted(self):
        config = SoorinModelConfig.from_env({
            "SOORIN_CHAT_ENABLED":"true", "SOORIN_CHAT_BASE_URL":"https://env.example/v1", "SOORIN_CHAT_MODEL":"env-model", "SOORIN_CHAT_API_KEY":"secret",
        }).with_workspace({"chat_base_url":"https://workspace.example/v1", "chat_model":"workspace-model"})
        self.assertEqual(config.chat.model, "workspace-model")
        self.assertNotIn("api_key", config.chat.public_dict())
        self.assertTrue(config.chat.public_dict()["has_api_key"])

    def test_invalid_url_reasoning_and_provider_fail_startup_validation(self):
        with self.assertRaises(ConfigurationError):
            ChatConfig(enabled=True, base_url="localhost:8000", model="m").validate()
        with self.assertRaises(ConfigurationError):
            ChatConfig(enabled=True, base_url="http://localhost", model="m", reasoning_effort="ultra").validate()
        with self.assertRaises(ConfigurationError):
            ChatConfig(provider="unknown").validate()
        with self.assertRaises(ConfigurationError):
            EmbeddingConfig(provider="unknown").validate()
        with self.assertRaises(ConfigurationError):
            RerankerConfig(provider="unknown").validate()
        with self.assertRaises(ConfigurationError):
            EmbeddingConfig(privacy_mode="allow").validate()
        with self.assertRaises(ConfigurationError):
            RerankerConfig(endpoint_trust="caller_says_safe").validate()

    def test_fake_embedding_response_dimension_and_order(self):
        def transport(url, headers, body, timeout):
            if len(body["input"]) == 1:
                return {"data":[{"index":0,"embedding":[1,0]}]}
            return {"data":[{"index":1,"embedding":[0,1]},{"index":0,"embedding":[1,0]}]}
        client = OpenAIEmbeddingClient(EmbeddingConfig(True, base_url="http://embed", model="m", dimension=2), transport)
        self.assertEqual(client.embed(["a", "b"]), [[1.0, 0.0], [0.0, 1.0]])
        self.assertEqual(client.health()["dimension"], 2)

    def test_embedding_dimension_mismatch_and_malformed_output(self):
        client = OpenAIEmbeddingClient(EmbeddingConfig(True, base_url="http://embed", model="m", dimension=3), lambda *args: {"data":[{"embedding":[1,0]}]})
        with self.assertRaisesRegex(ProviderError, "dimension_mismatch"):
            client.embed(["a"])
        bad = OpenAIEmbeddingClient(EmbeddingConfig(True, base_url="http://embed", model="m"), lambda *args: {"data":"bad"})
        with self.assertRaisesRegex(ProviderError, "malformed_response"):
            bad.embed(["a"])

    def test_chat_health_validates_fake_response(self):
        ready = OpenAIChatHealthClient(ChatConfig(True, base_url="http://chat", model="m"), lambda *args: {"choices":[{"message":{"content":"OK"}}]})
        self.assertEqual(ready.health()["status"], "ready")
        broken = OpenAIChatHealthClient(ChatConfig(True, base_url="http://chat", model="m"), lambda *args: {"choices":[]})
        self.assertEqual(broken.health()["error_code"], "malformed_response")

    def test_chat_block_all_prevents_transport(self):
        calls = []
        config = ChatConfig(
            True, base_url="http://chat", model="m", privacy_mode="block_all",
        )
        result = OpenAIChatHealthClient(config, lambda *args: calls.append(args) or {}).health()
        self.assertEqual(result["error_code"], "privacy_blocked")
        self.assertEqual(calls, [])

    def test_embedding_sensitive_external_text_is_blocked_before_transport(self):
        calls = []
        config = EmbeddingConfig(True, base_url="http://embed", model="m")
        client = OpenAIEmbeddingClient(config, lambda *args: calls.append(args) or {})
        with self.assertRaisesRegex(ProviderError, "privacy_blocked"):
            client.embed(["SOC alert on 192.0.2.44"])
        self.assertEqual(calls, [])

    def test_synthetic_embedding_requires_test_mode(self):
        transport = lambda *args: {"data": [{"index": 0, "embedding": [1, 0]}]}
        denied = EmbeddingConfig(
            True, base_url="http://embed", model="m", dimension=2, synthetic_mode=True,
        )
        with self.assertRaisesRegex(ProviderError, "privacy_blocked"):
            OpenAIEmbeddingClient(denied, transport).embed(["synthetic malware example"])
        allowed = EmbeddingConfig(
            True, base_url="http://embed", model="m", dimension=2,
            synthetic_mode=True, test_mode=True,
        )
        self.assertEqual(OpenAIEmbeddingClient(allowed, transport).embed(["synthetic malware example"]),
                         [[1.0, 0.0]])

    def test_transient_provider_errors_are_retried(self):
        calls = 0

        def transport(url, headers, body, timeout):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ProviderError("rate_limited", "synthetic 429")
            return {"data": [{"index": 0, "embedding": [1, 0]}]}

        config = EmbeddingConfig(True, base_url="http://embed", model="m", dimension=2, retries=1)
        self.assertEqual(OpenAIEmbeddingClient(config, transport).embed(["a"]), [[1.0, 0.0]])
        self.assertEqual(calls, 2)

    def test_authentication_failure_is_typed_without_echoing_provider_body(self):
        error = urllib.error.HTTPError(
            "http://embed", 401, "unauthorized", {}, BytesIO(b"echoed SOC alert secret"),
        )
        with patch("soorin.models.openai_compatible.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(ProviderError) as caught:
                _http_json("http://embed", {}, {"input": ["secret"]}, 1)
        self.assertEqual(caught.exception.code, "authentication_failed")
        self.assertNotIn("echoed SOC alert secret", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
