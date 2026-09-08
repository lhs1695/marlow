"""CI lexical fixture over slices; optional LangChain Chroma persist directory."""

from __future__ import annotations

from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from marlow.kb.embeddings import HashTokenEmbeddings
from marlow.kb.split import split_handbook

COLLECTION = "grafana_handbook"
_STOP = frozenset(
    {
        "a",
        "an",
        "and",
        "error",
        "errors",
        "failed",
        "failure",
        "for",
        "in",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
        "you",
        "your",
    }
)


def fixture_search(query: str, *, k: int = 8, chunks: tuple[Document, ...] | None = None) -> list[dict[str, str]]:
    needle = query.strip().lower()
    if not needle:
        return []
    tokens = [tok for tok in needle.split() if tok and tok not in _STOP]
    if not tokens:
        return []
    rows: list[tuple[int, Document]] = []
    for doc in chunks if chunks is not None else split_handbook():
        blob = f"{doc.page_content} {doc.metadata.get('doc_id', '')} {doc.metadata.get('version', '')}".lower()
        score = sum(1 for tok in tokens if tok in blob)
        if score:
            rows.append((score, doc))
    rows.sort(key=lambda item: item[0], reverse=True)
    return [_hit(doc) for _, doc in rows[:k]]


def build_chroma(
    persist_directory: str | Path,
    *,
    embeddings: Embeddings | None = None,
    chunks: tuple[Document, ...] | None = None,
) -> Chroma:
    docs = list(chunks if chunks is not None else split_handbook())
    path = Path(persist_directory)
    path.mkdir(parents=True, exist_ok=True)
    return Chroma.from_documents(
        documents=docs,
        embedding=embeddings or HashTokenEmbeddings(),
        persist_directory=str(path),
        collection_name=COLLECTION,
    )


def ensure_chroma_dir(persist_directory: str | Path, *, embeddings: Embeddings | None = None) -> Path:
    """Index handbook into an empty persist dir (Compose first start). Existing files are left alone."""
    path = Path(persist_directory)
    if path.exists() and any(path.iterdir()):
        return path
    build_chroma(path, embeddings=embeddings)
    return path


def search_chroma(
    query: str,
    persist_directory: str | Path,
    *,
    embeddings: Embeddings | None = None,
    k: int = 8,
) -> list[dict[str, str]]:
    needle = query.strip()
    if not needle:
        return []
    store = Chroma(
        collection_name=COLLECTION,
        embedding_function=embeddings or HashTokenEmbeddings(),
        persist_directory=str(persist_directory),
    )
    docs = store.similarity_search(needle, k=k)
    return [_hit(doc) for doc in docs]


def chroma_metadatas(persist_directory: str | Path, *, embeddings: Embeddings | None = None) -> list[dict]:
    store = Chroma(
        collection_name=COLLECTION,
        embedding_function=embeddings or HashTokenEmbeddings(),
        persist_directory=str(persist_directory),
    )
    dumped = store.get(include=["metadatas"])
    return list(dumped.get("metadatas") or [])


def _hit(doc: Document) -> dict[str, str]:
    return {
        "doc_id": str(doc.metadata["doc_id"]),
        "version": str(doc.metadata["version"]),
        "text": doc.page_content,
    }
