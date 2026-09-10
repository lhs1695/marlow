from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from marlow.codes import (
    APPROVAL_REQUIRED,
    DECISION_APPROVE,
    MAX_STEPS,
    PERM_EDITOR,
    PERM_VIEWER,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_RUNNING,
    RUN_WAITING_APPROVAL,
    SOURCE_TRUST_INTERNAL_GATEWAY,
    STATUS_RESOLVED,
    SYSTEM_GRAFANA,
    UNAUTHORIZED,
)
from marlow.engine import (
    RunLimits,
    claim_run_resume,
    latest_checkpoint,
    resume_run,
    start_run,
    ticket_status,
)
from marlow.fake import provider_for_case
from marlow.gateway import apply_entitlement_change, entitlement_permission
from marlow.models import Approval, AuditEvent, Run, RunEvent
from marlow.seed import ADMIN_ID, L1_ID
from tests.web_helpers import app_client, login_json, parse_sse, wait_for_run, wait_for_run_status


def _pause_change(session: Session, *, case_id: str = "change_hitl") -> Run:
    run = start_run(
        session,
        actor_id=L1_ID,
        user_text="工单 CHG-2004 申请给 emp-007 加 Grafana Editor",
        case_id=case_id,
        provider=provider_for_case(case_id),
    )
    session.flush()
    return run


def _decide(
    session: Session,
    run: Run,
    *,
    decision: str,
    key: str,
    ticket: str = "CHG-2004",
    target: str = "emp-007",
):
    return apply_entitlement_change(
        session,
        actor_id=ADMIN_ID,
        ticket_id=ticket,
        target_employee_id=target,
        system=SYSTEM_GRAFANA,
        new_permission=PERM_EDITOR,
        decision=decision,
        idempotency_key=key,
        run_id=run.id,
    )


def test_hitl_stays_waiting_approval_with_checkpoint(session) -> None:
    run = _pause_change(session)
    assert run.status == RUN_WAITING_APPROVAL
    assert run.status != RUN_COMPLETED
    assert run.outcome_code == APPROVAL_REQUIRED
    blob = latest_checkpoint(session, run.id)
    assert blob is not None
    assert blob["actor_id"] == L1_ID
    assert blob["ticket_id"] == "CHG-2004"
    assert blob["step_count"] == run.step_count
    assert blob["token_used"] == run.token_used
    assert blob["cost_cents"] == run.cost_cents
    assert blob["provider"]["kind"] == "fake"
    assert blob["provider"]["case_id"] == "change_hitl"
    assert blob["provider"]["index"] >= 1
    assert blob["last_action"]["name"] == "entitlement_change"
    assert "draft" in blob
    kinds = [row.kind for row in session.scalars(select(RunEvent).where(RunEvent.run_id == run.id))]
    assert kinds.count("checkpoint") == 1
    assert entitlement_permission(session, "emp-007", SYSTEM_GRAFANA) == PERM_VIEWER


def test_approval_row_stores_run_id(session) -> None:
    run = _pause_change(session)
    result = _decide(session, run, decision=DECISION_APPROVE, key="hitl-run-fk")
    session.flush()
    assert result.ok is True
    approval = session.scalar(select(Approval).where(Approval.idempotency_key == "hitl-run-fk"))
    assert approval is not None
    assert approval.run_id == run.id


def test_resume_brakes_inherit_step_token_cost(session) -> None:
    run = start_run(
        session,
        actor_id=L1_ID,
        user_text="工单 CHG-2004 申请给 emp-007 加 Grafana Editor",
        case_id="change_hitl",
        provider=provider_for_case("change_hitl"),
        limits=RunLimits(max_steps=1),
    )
    session.flush()
    assert run.status == RUN_WAITING_APPROVAL
    assert run.step_count == 1
    tokens = run.token_used
    cost = run.cost_cents
    _decide(session, run, decision=DECISION_APPROVE, key="hitl-brake")
    session.flush()
    assert claim_run_resume(session, run.id) is True
    resumed = resume_run(session, run_id=run.id, limits=RunLimits(max_steps=1))
    session.flush()
    assert resumed.status == RUN_FAILED
    assert resumed.outcome_code == MAX_STEPS
    assert resumed.step_count > 1
    assert resumed.token_used > tokens
    assert resumed.cost_cents > cost


def test_resume_observation_is_internal_gateway(session) -> None:
    run = _pause_change(session)
    _decide(session, run, decision=DECISION_APPROVE, key="hitl-gateway-obs")
    session.flush()
    assert claim_run_resume(session, run.id) is True
    resumed = resume_run(session, run_id=run.id)
    session.flush()
    obs = [
        json.loads(row.payload)
        for row in session.scalars(
            select(RunEvent).where(RunEvent.run_id == resumed.id, RunEvent.kind == "observation")
        )
        if "approval_gateway" in row.payload
    ]
    assert obs
    assert obs[0]["source_trust"] == SOURCE_TRUST_INTERNAL_GATEWAY
    assert obs[0]["code"] == "ok"


def test_claim_resume_optimistic_lock_second_loses(session) -> None:
    run = _pause_change(session)
    assert claim_run_resume(session, run.id) is True
    row = session.get(Run, run.id)
    assert row is not None
    assert row.status == RUN_RUNNING
    assert claim_run_resume(session, run.id) is False


def test_claim_resume_sql_requires_waiting_approval() -> None:
    source = (Path(__file__).resolve().parents[1] / "src" / "marlow" / "engine.py").read_text(
        encoding="utf-8"
    )
    assert "def claim_run_resume" in source
    assert "Run.status == RUN_WAITING_APPROVAL" in source
    stmt = (
        update(Run)
        .where(Run.id == "run-x", Run.status == RUN_WAITING_APPROVAL)
        .values(status=RUN_RUNNING)
    )
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "waiting_approval" in compiled
    assert "running" in compiled.lower()


def test_resume_keeps_l1_actor_and_cannot_write_entitlements(session) -> None:
    run = start_run(
        session,
        actor_id=L1_ID,
        user_text="工单 CHG-2004 申请给 emp-007 加 Grafana Editor",
        case_id="change_hitl_forge",
        provider=provider_for_case("change_hitl_forge"),
    )
    session.flush()
    _decide(session, run, decision=DECISION_APPROVE, key="hitl-forge")
    session.flush()
    assert entitlement_permission(session, "emp-007", SYSTEM_GRAFANA) == PERM_EDITOR
    assert claim_run_resume(session, run.id) is True
    resumed = resume_run(session, run_id=run.id)
    session.flush()
    assert resumed.actor_id == L1_ID
    assert resumed.actor_id != ADMIN_ID
    assert entitlement_permission(session, "emp-007", SYSTEM_GRAFANA) == PERM_EDITOR
    assert resumed.outcome_code == UNAUTHORIZED
    denies = list(
        session.scalars(
            select(AuditEvent).where(
                AuditEvent.action == "apply_entitlement_change",
                AuditEvent.outcome == "deny",
                AuditEvent.actor_id == L1_ID,
            )
        )
    )
    assert denies
    approved = list(
        session.scalars(
            select(AuditEvent).where(
                AuditEvent.action == "apply_entitlement_change",
                AuditEvent.ticket_id == "CHG-2004",
                AuditEvent.outcome == "approved",
            )
        )
    )
    assert len(approved) == 1
    assert approved[0].actor_role == "admin"


def test_sse_reconnect_after_pause_sees_resume_events_on_same_run() -> None:
    with app_client() as (client, engine):
        login_json(client, "l1", "l1-demo")
        created = client.post(
            "/api/runs",
            json={"text": "工单 CHG-2004 申请给 emp-007 加 Grafana Editor"},
        )
        assert created.status_code == 202, created.text
        run_id = created.json()["run_id"]
        wait_for_run_status(client, run_id, RUN_WAITING_APPROVAL)
        last_id = 0
        with Session(engine) as db:
            ids = list(
                db.scalars(select(RunEvent.id).where(RunEvent.run_id == run_id).order_by(RunEvent.id))
            )
            assert ids
            last_id = ids[-1]
            row = db.get(Run, run_id)
            assert row is not None
            assert row.status == RUN_WAITING_APPROVAL
            assert row.id == run_id
        login_json(client, "admin", "admin-demo")
        decided = client.post(
            "/api/entitlements",
            json={
                "ticket_id": "CHG-2004",
                "target_employee_id": "emp-007",
                "system": SYSTEM_GRAFANA,
                "new_permission": PERM_EDITOR,
                "decision": DECISION_APPROVE,
                "idempotency_key": "sse-last-event-resume",
            },
        )
        assert decided.status_code == 200, decided.text
        final = wait_for_run(client, run_id)
        assert final["status"] == RUN_COMPLETED
        resumed = client.get(
            f"/api/runs/{run_id}/events",
            headers={"Last-Event-ID": str(last_id)},
        )
        assert resumed.status_code == 200
        events = parse_sse(resumed.text)
        new_ids = [item["id"] for item in events if item["id"] is not None]
        assert new_ids
        assert all(event_id > last_id for event_id in new_ids)
        assert events[-1]["event"] == "done"
        kinds = [item["data"].get("kind") for item in events]
        assert "observation" in kinds or any(item["event"] == "tool" for item in events)
        with Session(engine) as db:
            row = db.get(Run, run_id)
            assert row is not None
            assert row.id == run_id
            assert row.actor_id == L1_ID
            assert ticket_status(db, "CHG-2004") == STATUS_RESOLVED
