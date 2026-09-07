"""Handbook retrieval: split pinned Grafana docs; CI uses a lexical fixture; optional Chroma persist."""

from marlow.kb.embeddings import HashTokenEmbeddings, openai_compat_embeddings
from marlow.kb.load import HANDBOOK_VERSION, INJECTION_SLICE, handbook_root, load_handbook_documents
from marlow.kb.split import split_handbook
from marlow.kb.store import build_chroma, fixture_search, search_chroma

__all__ = [
    "HANDBOOK_VERSION",
    "INJECTION_SLICE",
    "HashTokenEmbeddings",
    "build_chroma",
    "fixture_search",
    "handbook_root",
    "load_handbook_documents",
    "openai_compat_embeddings",
    "search_chroma",
    "split_handbook",
]
