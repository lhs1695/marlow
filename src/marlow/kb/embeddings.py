"""Embedding backends: hash fixture for CI; OpenAI-compatible only when explicitly requested."""

from __future__ import annotations

import hashlib
import os

from langchain_core.embeddings import Embeddings

from marlow.credentials import resolve_api_key

_DIM = 64
KB_EMBEDDINGS_ENV = "MARLOW_KB_EMBEDDINGS"
_QUERY_PREFIX = "query: "
_PASSAGE_PREFIX = "passage: "


class HashTokenEmbeddings(Embeddings):
    """Deterministic bag-of-tokens vectors. No API. Not a production embedding model."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * _DIM
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:2], "little") % _DIM
            vec[idx] += 1.0
        norm = sum(v * v for v in vec) ** 0.5
        if norm:
            vec = [v / norm for v in vec]
        return vec


class QueryPassageEmbeddings(Embeddings):
    """Official query/passage prefixes for real embeddings only. Does not change stored page_content."""

    def __init__(self, inner: Embeddings) -> None:
        self._inner = inner

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._inner.embed_documents([_PASSAGE_PREFIX + text for text in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._inner.embed_query(_QUERY_PREFIX + text)


def _compat_client() -> Embeddings:
    try:
        from langchain_openai import OpenAIEmbeddings
    except ImportError as exc:
        raise RuntimeError("install openai extra (langchain-openai) for --real embeddings") from exc
    api_key = resolve_api_key()
    if not api_key:
        raise RuntimeError("XAI_API_KEY or OPENAI_API_KEY required for --real embeddings")
    kwargs: dict[str, str] = {"api_key": api_key}
    base = os.environ.get("OPENAI_BASE_URL")
    if base:
        kwargs["base_url"] = base
    model = os.environ.get("MARLOW_EMBEDDING_MODEL")
    if model:
        kwargs["model"] = model
    return OpenAIEmbeddings(**kwargs)


def openai_compat_embeddings() -> Embeddings:
    return QueryPassageEmbeddings(_compat_client())


def resolve_kb_embeddings(*, real: bool = False) -> Embeddings:
    if real:
        return openai_compat_embeddings()
    value = os.environ.get(KB_EMBEDDINGS_ENV, "").strip().lower()
    if value in {"real", "openai", "1", "true"}:
        return openai_compat_embeddings()
    return HashTokenEmbeddings()
