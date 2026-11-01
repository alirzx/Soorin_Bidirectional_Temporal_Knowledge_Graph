"""Typed model configuration and explicit precedence.

Environment values establish application defaults. Authorized Utopia
workspace settings override only fields present in that workspace. Secrets are
never included in ``public_dict``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import os
from typing import Any, Mapping
from urllib.parse import urlsplit


class ConfigurationError(ValueError):
    pass


def _bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().casefold()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(f"invalid boolean {value!r}")


def _int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        result = default if value in (None, "") else int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigurationError(f"invalid integer {value!r}") from exc
    if not minimum <= result <= maximum:
        raise ConfigurationError(f"integer {result} outside {minimum}..{maximum}")
    return result


def _url(value: str | None, enabled: bool) -> str | None:
    if not value:
        if enabled:
            raise ConfigurationError("enabled provider requires base_url")
        return None
    value = value.rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigurationError("base_url must be an absolute HTTP(S) URL")
    return value


@dataclass(frozen=True, slots=True)
class ChatConfig:
    enabled: bool = False
    provider: str = "openai_compatible"
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    reasoning_effort: str | None = None
    timeout_seconds: int = 60
    retries: int = 2
    max_concurrency: int = 4
    max_output_tokens: int = 4096
    structured_output: str = "json_schema"
    tls_verify: bool = True

    def validate(self) -> "ChatConfig":
        _url(self.base_url, self.enabled)
        if self.provider != "openai_compatible":
            raise ConfigurationError("unsupported chat provider")
        if self.enabled and not self.model:
            raise ConfigurationError("enabled chat provider requires model")
        if self.reasoning_effort not in {None, "none", "minimal", "low", "medium", "high"}:
            raise ConfigurationError("unsupported reasoning_effort")
        if self.structured_output not in {"json_schema", "json_object", "prompt_only", "disabled"}:
            raise ConfigurationError("unsupported structured_output behavior")
        return self

    def public_dict(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in self.__slots__ if key != "api_key"} | {"has_api_key": bool(self.api_key)}


@dataclass(frozen=True, slots=True)
class EmbeddingConfig:
    enabled: bool = False
    provider: str = "openai_compatible"
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    dimension: int | None = None
    timeout_seconds: int = 30
    retries: int = 2
    batch_size: int = 32
    max_concurrency: int = 4
    normalize: bool = True
    cache_enabled: bool = True

    def validate(self) -> "EmbeddingConfig":
        _url(self.base_url, self.enabled)
        if self.provider != "openai_compatible":
            raise ConfigurationError("unsupported embedding provider")
        if self.enabled and not self.model:
            raise ConfigurationError("enabled embedding provider requires model")
        if self.dimension is not None and not 1 <= self.dimension <= 65536:
            raise ConfigurationError("embedding dimension must be 1..65536")
        return self

    def public_dict(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in self.__slots__ if key != "api_key"} | {"has_api_key": bool(self.api_key)}


@dataclass(frozen=True, slots=True)
class RerankerConfig:
    enabled: bool = False
    provider: str = "cohere_v2"
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    timeout_seconds: int = 10
    top_n: int = 10
    batch_size: int = 32
    max_concurrency: int = 2
    fallback_enabled: bool = True
    max_document_chars: int = 8000

    def validate(self) -> "RerankerConfig":
        _url(self.base_url, self.enabled)
        if self.enabled and not self.model:
            raise ConfigurationError("enabled reranker requires model")
        if self.provider not in {"cohere_v2", "jina_v1", "tei"}:
            raise ConfigurationError("unsupported reranker provider")
        return self

    def public_dict(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in self.__slots__ if key != "api_key"} | {"has_api_key": bool(self.api_key)}


@dataclass(frozen=True, slots=True)
class SoorinModelConfig:
    chat: ChatConfig
    embedding: EmbeddingConfig
    reranker: RerankerConfig

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "SoorinModelConfig":
        e = os.environ if env is None else env
        chat = ChatConfig(
            enabled=_bool(e.get("SOORIN_CHAT_ENABLED"), False), provider=e.get("SOORIN_CHAT_PROVIDER", "openai_compatible"),
            base_url=e.get("SOORIN_CHAT_BASE_URL"), model=e.get("SOORIN_CHAT_MODEL"), api_key=e.get("SOORIN_CHAT_API_KEY"),
            reasoning_effort=e.get("SOORIN_CHAT_REASONING_EFFORT") or None,
            timeout_seconds=_int(e.get("SOORIN_CHAT_TIMEOUT_SECONDS"), 60, minimum=1, maximum=3600),
            retries=_int(e.get("SOORIN_CHAT_RETRIES"), 2, minimum=0, maximum=10),
            max_concurrency=_int(e.get("SOORIN_CHAT_MAX_CONCURRENCY"), 4, minimum=1, maximum=256),
            max_output_tokens=_int(e.get("SOORIN_CHAT_MAX_OUTPUT_TOKENS"), 4096, minimum=1, maximum=262144),
            structured_output=e.get("SOORIN_CHAT_STRUCTURED_OUTPUT", "json_schema"),
            tls_verify=_bool(e.get("SOORIN_CHAT_TLS_VERIFY"), True),
        ).validate()
        dim = e.get("SOORIN_EMBED_DIM")
        embedding = EmbeddingConfig(
            enabled=_bool(e.get("SOORIN_EMBED_ENABLED"), False), provider=e.get("SOORIN_EMBED_PROVIDER", "openai_compatible"),
            base_url=e.get("SOORIN_EMBED_BASE_URL"), model=e.get("SOORIN_EMBED_MODEL"), api_key=e.get("SOORIN_EMBED_API_KEY"),
            dimension=None if dim in (None, "") else _int(dim, 1, minimum=1, maximum=65536),
            timeout_seconds=_int(e.get("SOORIN_EMBED_TIMEOUT_SECONDS"), 30, minimum=1, maximum=3600),
            retries=_int(e.get("SOORIN_EMBED_RETRIES"), 2, minimum=0, maximum=10),
            batch_size=_int(e.get("SOORIN_EMBED_BATCH_SIZE"), 32, minimum=1, maximum=2048),
            max_concurrency=_int(e.get("SOORIN_EMBED_MAX_CONCURRENCY"), 4, minimum=1, maximum=256),
            normalize=_bool(e.get("SOORIN_EMBED_NORMALIZE"), True), cache_enabled=_bool(e.get("SOORIN_EMBED_CACHE_ENABLED"), True),
        ).validate()
        reranker = RerankerConfig(
            enabled=_bool(e.get("SOORIN_RERANK_ENABLED"), False), provider=e.get("SOORIN_RERANK_PROVIDER", "cohere_v2"),
            base_url=e.get("SOORIN_RERANK_BASE_URL"), model=e.get("SOORIN_RERANK_MODEL"), api_key=e.get("SOORIN_RERANK_API_KEY"),
            timeout_seconds=_int(e.get("SOORIN_RERANK_TIMEOUT_SECONDS"), 10, minimum=1, maximum=3600),
            top_n=_int(e.get("SOORIN_RERANK_TOP_N"), 10, minimum=1, maximum=1000),
            batch_size=_int(e.get("SOORIN_RERANK_BATCH_SIZE"), 32, minimum=1, maximum=2048),
            max_concurrency=_int(e.get("SOORIN_RERANK_MAX_CONCURRENCY"), 2, minimum=1, maximum=256),
            fallback_enabled=_bool(e.get("SOORIN_RERANK_FALLBACK_ENABLED"), True),
            max_document_chars=_int(e.get("SOORIN_RERANK_MAX_DOCUMENT_CHARS"), 8000, minimum=128, maximum=100000),
        ).validate()
        return cls(chat, embedding, reranker)

    def with_workspace(self, workspace: Mapping[str, Any]) -> "SoorinModelConfig":
        """Apply authorized Utopia workspace fields over environment defaults."""

        chat_map = {
            "chat_base_url": "base_url", "chat_model": "model", "chat_api_key": "api_key",
            "chat_reasoning_effort": "reasoning_effort",
        }
        embed_map = {
            "embed_base_url": "base_url", "embed_model": "model", "embed_api_key": "api_key", "embed_dim": "dimension",
        }
        chat_updates = {target: workspace[source] for source, target in chat_map.items() if workspace.get(source) not in (None, "")}
        embed_updates = {target: workspace[source] for source, target in embed_map.items() if workspace.get(source) not in (None, "")}
        chat = replace(self.chat, **chat_updates, enabled=bool((chat_updates.get("base_url") or self.chat.base_url) and (chat_updates.get("model") or self.chat.model))).validate()
        embedding = replace(self.embedding, **embed_updates, enabled=bool((embed_updates.get("base_url") or self.embedding.base_url) and (embed_updates.get("model") or self.embedding.model))).validate()
        return SoorinModelConfig(chat, embedding, self.reranker)
