from __future__ import annotations

import unittest

from soorin.models import OpenAIChatHealthClient, OpenAIEmbeddingClient
from soorin.models.configuration import ChatConfig, ConfigurationError, EmbeddingConfig, RerankerConfig, SoorinModelConfig
from soorin.models.openai_compatible import ProviderError


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


if __name__ == "__main__":
    unittest.main()
