"""Embedding backends: hash fixture for CI; OpenAI-compatible only when explicitly requested."""

from __future__ import annotations

import hashlib
import os

from langchain_core.embeddings import Embeddings

_DIM = 64


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


def openai_compat_embeddings() -> Embeddings:
    try:
        from langchain_openai import OpenAIEmbeddings
    except ImportError as exc:
        raise RuntimeError("install openai extra (langchain-openai) for --real embeddings") from exc
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY required for --real embeddings")
    kwargs: dict[str, str] = {"api_key": api_key}
    base = os.environ.get("OPENAI_BASE_URL")
    if base:
        kwargs["base_url"] = base
    model = os.environ.get("MARLOW_EMBEDDING_MODEL")
    if model:
        kwargs["model"] = model
    return OpenAIEmbeddings(**kwargs)
