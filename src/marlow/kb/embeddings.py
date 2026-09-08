"""Embedding backends: hash fixture for CI; OpenAI-compatible only when explicitly requested."""

from __future__ import annotations

import hashlib
import os
from typing import Any

from langchain_core.embeddings import Embeddings

from marlow.credentials import resolve_embedding_api_key

_DIM = 64
KB_EMBEDDINGS_ENV = "MARLOW_KB_EMBEDDINGS"
EMBEDDING_BASE_ENV = "MARLOW_EMBEDDING_BASE_URL"
EMBEDDING_MODEL_ENV = "MARLOW_EMBEDDING_MODEL"
TASK_QUERY = "retrieval.query"
TASK_PASSAGE = "retrieval.passage"


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


class RetrievalTaskEmbeddings(Embeddings):
    """Jina retrieval adapters via extra_body task. Does not change stored page_content."""

    def __init__(self, *, query: Embeddings, passage: Embeddings) -> None:
        self._query = query
        self._passage = passage

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._passage.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._query.embed_query(text)


class _OpenAICompatEmbeddings(Embeddings):
    def __init__(self, *, client: Any, model: str, task: str) -> None:
        self._client = client
        self._model = model
        self._task = task

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self._client.embeddings.create(
            model=self._model,
            input=texts,
            extra_body={"task": self._task},
        )
        rows = sorted(response.data, key=lambda item: int(getattr(item, "index", 0) or 0))
        return [list(row.embedding) for row in rows]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def _make_embed_http_client() -> Any:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("install llm extra: uv sync --extra llm") from exc
    api_key = resolve_embedding_api_key()
    if not api_key:
        raise RuntimeError("JINA_API_KEY or OPENAI_API_KEY required for --real embeddings")
    base = os.environ.get(EMBEDDING_BASE_ENV, "").strip()
    if not base:
        raise RuntimeError("MARLOW_EMBEDDING_BASE_URL must be set for real embeddings")
    return OpenAI(api_key=api_key, base_url=base)


def _compat_client(*, task: str) -> Embeddings:
    model = os.environ.get(EMBEDDING_MODEL_ENV, "").strip()
    if not model:
        raise RuntimeError("MARLOW_EMBEDDING_MODEL must be set for real embeddings")
    return _OpenAICompatEmbeddings(client=_make_embed_http_client(), model=model, task=task)


def openai_compat_embeddings() -> Embeddings:
    return RetrievalTaskEmbeddings(
        query=_compat_client(task=TASK_QUERY),
        passage=_compat_client(task=TASK_PASSAGE),
    )


def resolve_kb_embeddings(*, real: bool = False) -> Embeddings:
    if real:
        return openai_compat_embeddings()
    value = os.environ.get(KB_EMBEDDINGS_ENV, "").strip().lower()
    if value in {"real", "openai", "1", "true"}:
        return openai_compat_embeddings()
    return HashTokenEmbeddings()
