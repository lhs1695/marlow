from langchain_core.embeddings import Embeddings

from marlow.codes import KB_MISS, KB_VERSION_MISMATCH, STATUS_INVESTIGATING
from marlow.engine import comment_count, start_run, ticket_status
from marlow.fake import provider_for_case
from marlow.kb.embeddings import HashTokenEmbeddings, openai_compat_embeddings, resolve_kb_embeddings
from marlow.kb.load import HANDBOOK_VERSION, INJECTION_SLICE, load_handbook_documents
from marlow.kb.split import split_handbook
from marlow.kb.store import build_chroma, chroma_metadatas
from marlow.seed import L1_ID
from marlow.tools.kb import search_kb


def test_handbook_pin_version_and_themes() -> None:
    docs = load_handbook_documents()
    assert all(row.metadata["version"] == HANDBOOK_VERSION == "10.4" for row in docs)
    joined = "\n".join(row.page_content for row in docs)
    assert "http://localhost:3000" in joined
    assert "Viewer" in joined and "Editor" in joined and "Admin" in joined
    assert "Datasource connection failed" in joined
    assert INJECTION_SLICE in joined
    assert "INC-" not in joined
    assert "CHG-" not in joined


def test_split_chunks_keep_doc_id_and_version() -> None:
    chunks = split_handbook()
    assert len(chunks) >= len(load_handbook_documents())
    for chunk in chunks:
        assert chunk.metadata["doc_id"]
        assert chunk.metadata["version"] == "10.4"


def test_search_kb_hit_from_slices_is_untrusted() -> None:
    hit = search_kb(query="grafana login localhost")
    assert hit.ok is True
    assert hit.untrusted is True
    assert hit.data["hits"]
    for row in hit.data["hits"]:
        assert row["doc_id"]
        assert row["version"] == "10.4"
    assert any("localhost:3000" in row["text"] for row in hit.data["hits"])


def test_search_kb_miss_empty_hits() -> None:
    miss = search_kb(query="coffee machine E7")
    assert miss.ok is False
    assert miss.code == KB_MISS
    assert miss.untrusted is True
    assert miss.data["hits"] == []


def test_ensure_chroma_dir_indexes_once(tmp_path) -> None:
    persist = tmp_path / "chroma"
    from marlow.kb.store import ensure_chroma_dir

    first = ensure_chroma_dir(persist)
    marker = persist / "keep-me.txt"
    marker.write_text("stay", encoding="utf-8")
    ensure_chroma_dir(persist)
    assert first == persist
    assert marker.read_text(encoding="utf-8") == "stay"


def test_chroma_persist_has_version_metadata_not_tickets(tmp_path) -> None:
    persist = tmp_path / "chroma"
    build_chroma(persist)
    metas = chroma_metadatas(persist)
    assert metas
    for meta in metas:
        assert meta.get("doc_id")
        assert meta.get("version") == "10.4"
        assert "ticket_id" not in meta
        assert not str(meta.get("doc_id", "")).startswith("INC-")
    obs = search_kb(query="prometheus datasource connection failed", persist_directory=persist)
    assert obs.ok is True
    assert obs.untrusted is True
    assert any(row["doc_id"] == "grafana-datasource" and row["version"] == "10.4" for row in obs.data["hits"])


def test_kb_qa_miss_still_refuses(session) -> None:
    run = start_run(
        session,
        actor_id=L1_ID,
        user_text="INC-1003 咖啡机怎么修",
        case_id="kb_qa_miss",
        provider=provider_for_case("kb_qa_miss"),
    )
    session.flush()
    assert run.outcome_code == KB_MISS
    assert "未编造" in (run.final_answer or "")


def test_close_version_mismatch_does_not_resolve_via_slices(session) -> None:
    comments_before = comment_count(session)
    run = start_run(
        session,
        actor_id=L1_ID,
        user_text="按旧手册关 INC-1004",
        case_id="close_version_mismatch",
        provider=provider_for_case("close_version_mismatch"),
    )
    session.flush()
    assert run.outcome_code == KB_VERSION_MISMATCH
    assert ticket_status(session, "INC-1004") == STATUS_INVESTIGATING
    assert comment_count(session) == comments_before


def test_openai_compat_embeddings_accepts_xai_key_only(monkeypatch) -> None:
    import sys
    from types import ModuleType

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("XAI_API_KEY", "xai-only-key-aaaaaaaa")
    captured: dict[str, str] = {}

    class FakeOpenAIEmbeddings:
        def __init__(self, **kwargs: str) -> None:
            captured.update(kwargs)

    existing = sys.modules.get("langchain_openai")
    if existing is None:
        mod = ModuleType("langchain_openai")
        mod.OpenAIEmbeddings = FakeOpenAIEmbeddings  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "langchain_openai", mod)
    else:
        monkeypatch.setattr(existing, "OpenAIEmbeddings", FakeOpenAIEmbeddings)

    openai_compat_embeddings()
    assert captured["api_key"] == "xai-only-key-aaaaaaaa"


def test_resolve_kb_embeddings_without_env_is_hash(monkeypatch) -> None:
    monkeypatch.delenv("MARLOW_KB_EMBEDDINGS", raising=False)
    assert isinstance(resolve_kb_embeddings(), HashTokenEmbeddings)


def test_search_kb_uses_compat_embeddings_when_env_set(tmp_path, monkeypatch) -> None:
    queries: list[str] = []

    class CompatStub(Embeddings):
        def __init__(self) -> None:
            self._inner = HashTokenEmbeddings()

        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return self._inner.embed_documents(texts)

        def embed_query(self, text: str) -> list[float]:
            queries.append(text)
            return self._inner.embed_query(text)

    stub = CompatStub()
    monkeypatch.setenv("MARLOW_KB_EMBEDDINGS", "real")
    monkeypatch.setattr("marlow.tools.kb.resolve_kb_embeddings", lambda: stub)
    persist = tmp_path / "chroma"
    build_chroma(persist, embeddings=stub)
    obs = search_kb(query="grafana login localhost", persist_directory=persist)
    assert obs.ok is True
    assert obs.untrusted is True
    assert queries
    assert not isinstance(stub, HashTokenEmbeddings)


def test_kb_main_real_uses_same_resolver(tmp_path, monkeypatch) -> None:
    seen: dict[str, bool] = {}
    queries: list[str] = []

    class CompatStub(Embeddings):
        def __init__(self) -> None:
            self._inner = HashTokenEmbeddings()

        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return self._inner.embed_documents(texts)

        def embed_query(self, text: str) -> list[float]:
            queries.append(text)
            return self._inner.embed_query(text)

    stub = CompatStub()

    def fake_resolve(*, real: bool = False) -> Embeddings:
        seen["real"] = real
        return stub

    monkeypatch.setattr("marlow.kb.embeddings.resolve_kb_embeddings", fake_resolve)
    monkeypatch.setattr("marlow.tools.kb.resolve_kb_embeddings", fake_resolve)
    monkeypatch.setattr("marlow.credentials.load_local_env", lambda: None)
    from marlow.kb.__main__ import main

    persist = tmp_path / "idx"
    assert main(["--persist", str(persist), "--real"]) == 0
    assert seen["real"] is True
    obs = search_kb(query="grafana login localhost", persist_directory=persist)
    assert obs.ok is True
    assert queries
