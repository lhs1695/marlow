import json

from sqlalchemy import select

from marlow.codes import (
    APPROVAL_REQUIRED,
    KB_MISS,
    KB_VERSION_MISMATCH,
    NOT_ENOUGH_INFO,
    PERM_VIEWER,
    SKILL_CLOSE,
    SKILL_ENTITLEMENT_CHANGE,
    SKILL_INVESTIGATE,
    SKILL_KB_QA,
    SKILL_VERSION,
    STATUS_INVESTIGATING,
    STATUS_RESOLVED,
    SYSTEM_GRAFANA,
)
from marlow.engine import comment_count, start_run, ticket_status
from marlow.fake import provider_for_case
from marlow.gateway import entitlement_permission
from marlow.models import MemoryNote, RunEvent, TicketComment
from marlow.seed import L1_ID
from marlow.skills import SKILLS, match_skill


def test_skills_match_by_name_and_version() -> None:
    assert set(SKILLS) == {SKILL_INVESTIGATE, SKILL_KB_QA, SKILL_CLOSE, SKILL_ENTITLEMENT_CHANGE}
    for spec in SKILLS.values():
        assert spec.version == SKILL_VERSION
        assert spec.draft_schema["type"] == "object"
        assert match_skill(spec.name, spec.version) is spec
    assert match_skill(SKILL_CLOSE, "0.0") is None
    assert match_skill("not-a-skill") is None


def test_close_skill_without_citation_stays_investigating(session) -> None:
    comments_before = comment_count(session)
    run = start_run(
        session,
        actor_id=L1_ID,
        user_text="请关 INC-1001",
        case_id="close_missing_cite",
        provider=provider_for_case("close_missing_cite"),
    )
    session.flush()
    assert run.outcome_code == NOT_ENOUGH_INFO
    assert ticket_status(session, "INC-1001") == STATUS_INVESTIGATING
    assert comment_count(session) == comments_before
    assert entitlement_permission(session, "emp-003", SYSTEM_GRAFANA) == PERM_VIEWER


def test_close_skill_with_evidence_resolves_and_cites_kb(session) -> None:
    run = start_run(
        session,
        actor_id=L1_ID,
        user_text="请调查 INC-1001 并关单",
        case_id="close_success",
        provider=provider_for_case("close_success"),
    )
    session.flush()
    assert run.outcome_code == "ok"
    assert ticket_status(session, "INC-1001") == STATUS_RESOLVED
    comments = list(session.scalars(select(TicketComment).where(TicketComment.ticket_id == "INC-1001")))
    closing = [row.body for row in comments if "ticket_id=INC-1001" in row.body]
    assert closing
    assert "grafana-login@10.4" in closing[-1]
    assert "kb=" in closing[-1]


def test_close_skill_version_mismatch_does_not_resolve(session) -> None:
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


def test_change_skill_does_not_write_entitlements(session) -> None:
    before = entitlement_permission(session, "emp-007", SYSTEM_GRAFANA)
    run = start_run(
        session,
        actor_id=L1_ID,
        user_text="工单 CHG-2004 申请给 emp-007 加 Grafana Editor",
        case_id="change_hitl",
        provider=provider_for_case("change_hitl"),
    )
    session.flush()
    assert run.outcome_code == APPROVAL_REQUIRED
    assert entitlement_permission(session, "emp-007", SYSTEM_GRAFANA) == before == PERM_VIEWER
    assert ticket_status(session, "CHG-2004") != STATUS_RESOLVED


def test_kb_qa_miss_refuses_without_inventing(session) -> None:
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
    assert ticket_status(session, "INC-1003") != STATUS_RESOLVED


def test_investigate_injects_memory_notes_untrusted(session) -> None:
    first = start_run(
        session,
        actor_id=L1_ID,
        user_text="请调查 INC-1001",
        case_id="investigate",
        provider=provider_for_case("investigate"),
    )
    session.flush()
    assert first.outcome_code == "ok"
    assert "INC-1001" in (first.final_answer or "")
    assert "grafana-login@10.4" in (first.final_answer or "")
    notes = list(session.scalars(select(MemoryNote)))
    assert notes

    second = start_run(
        session,
        actor_id=L1_ID,
        user_text="同一请求人的 INC-1005",
        case_id="investigate_followup",
        provider=provider_for_case("investigate_followup"),
    )
    session.flush()
    payloads = [
        json.loads(row.payload)
        for row in session.scalars(select(RunEvent).where(RunEvent.run_id == second.id, RunEvent.kind == "memory"))
    ]
    assert payloads
    assert payloads[0]["untrusted"] is True
    assert payloads[0]["notes"]
    assert "untrusted" in (second.final_answer or "")
