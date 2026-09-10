"""search_kb over handbook slices. CI uses the lexical fixture; optional Chroma persist via MARLOW_CHROMA_DIR."""

from __future__ import annotations

import os
from pathlib import Path

from marlow.codes import KB_MISS
from marlow.kb.load import INJECTION_SLICE
from marlow.kb.embeddings import resolve_kb_embeddings
from marlow.kb.store import fixture_search, search_chroma
from marlow.observation import Observation

__all__ = ["INJECTION_SLICE", "search_kb"]


def search_kb(*, query: str, persist_directory: str | Path | None = None) -> Observation:
    persist = persist_directory if persist_directory is not None else os.environ.get("MARLOW_CHROMA_DIR")
    if persist:
        hits = search_chroma(query, persist, embeddings=resolve_kb_embeddings())
    else:
        hits = fixture_search(query)
    if not hits:
        return Observation(ok=False, code=KB_MISS, retryable=False, data={"hits": []})
    return Observation(ok=True, code="ok", retryable=False, data={"hits": hits})
