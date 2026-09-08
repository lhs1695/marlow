from marlow.codes import KB_MISS, KB_VERSION_MISMATCH, STATUS_INVESTIGATING
from marlow.engine import comment_count, start_run, ticket_status
from marlow.fake import provider_for_case
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
