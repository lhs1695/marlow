"""LangChain text splitters over the pinned handbook."""

from __future__ import annotations

from functools import lru_cache

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from marlow.kb.load import load_handbook_documents

_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=800,
    chunk_overlap=120,
    separators=["\n## ", "\n### ", "\n\n", "\n", " "],
)


@lru_cache(maxsize=1)
def split_handbook() -> tuple[Document, ...]:
    chunks = _SPLITTER.split_documents(list(load_handbook_documents()))
    for chunk in chunks:
        if not chunk.metadata.get("doc_id") or not chunk.metadata.get("version"):
            raise ValueError("handbook chunk missing doc_id or version")
    return tuple(chunks)
