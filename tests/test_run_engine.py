import json

from sqlalchemy import func, select

from marlow.codes import (
    APPROVAL_REQUIRED,
    MAX_STEPS,
    NOT_ENOUGH_INFO,
    PERM_VIEWER,
    RETRYABLE_TIMEOUT,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_WAITING_APPROVAL,
    STATUS_INVESTIGATING,
    SYSTEM_GRAFANA,
    UNAUTHORIZED,
)
from marlow.engine import comment_count, start_run, ticket_status
from marlow.fake import provider_for_case
from marlow.faults import FAULT_TIMEOUT, FaultHooks
from marlow.gateway import entitlement_permission
from marlow.models import AuditEvent, MemoryNote, RunEvent, Ticket
from marlow.seed import L1_ID


def test_missing_ticket_id_clarifies_without_ticket_writes(session) -> None:
    comments_before = comment_count(session)
    tickets_before = session.scalar(select(func.count()).select_from(Ticket))
    run = start_run(
        session,
        actor_id=L1_ID,
        user_text="Grafana 登录有问题，帮我看看",
        case_id="clarify",
    )
    session.flush()
    assert run.status == RUN_COMPLETED
    assert run.outcome_code == NOT_ENOUGH_INFO
    assert "工单号" in (run.final_answer or "")
    kinds = [row.kind for row in session.scalars(select(RunEvent).where(RunEvent.run_id == run.id))]
    assert "clarify" in kinds
    assert comment_count(session) == comments_before
    assert session.scalar(select(func.count()).select_from(Ticket)) == tickets_before
    assert session.scalar(select(func.count()).select_from(MemoryNote)) == 0


def test_timeout_degrades_without_inventing_asset(session) -> None:
    hooks = FaultHooks()
    hooks.set_target("get_asset", "ast-laptop-casey", FAULT_TIMEOUT)
    run = start_run(
        session,
        actor_id=L1_ID,
        user_text="读取 INC-1005 的资产配置",
        case_id="timeout",
        faults=hooks,
        provider=provider_for_case("timeout"),
    )
    session.flush()
    assert run.status == RUN_COMPLETED
    assert run.outcome_code == RETRYABLE_TIMEOUT
    answer = run.final_answer or ""
    assert "降级" in answer
    assert "casey-nb" not in answer
    assert "grafana.example.com" not in answer
    assert ticket_status(session, "INC-1005") == STATUS_INVESTIGATING
    payloads = [
        json.loads(row.payload)
        for row in session.scalars(select(RunEvent).where(RunEvent.run_id == run.id, RunEvent.kind == "retry"))
    ]
    assert payloads


def test_l1_fake_change_tool_denied(session) -> None:
    run = start_run(
        session,
        actor_id=L1_ID,
        user_text="在 CHG-2004 上直接改权限",
        case_id="l1_deny",
        provider=provider_for_case("l1_deny"),
    )
    session.flush()
    assert run.outcome_code == UNAUTHORIZED
    assert entitlement_permission(session, "emp-007", SYSTEM_GRAFANA) == PERM_VIEWER
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


def test_change_run_enters_waiting_approval(session) -> None:
    run = start_run(
        session,
        actor_id=L1_ID,
        user_text="工单 CHG-2004 申请给 emp-007 加 Grafana Editor",
        case_id="change_hitl",
        provider=provider_for_case("change_hitl"),
    )
    session.flush()
    states = [
        json.loads(row.payload).get("status")
        for row in session.scalars(select(RunEvent).where(RunEvent.run_id == run.id, RunEvent.kind == "state"))
    ]
    assert RUN_WAITING_APPROVAL in states
    assert run.outcome_code == APPROVAL_REQUIRED
    assert entitlement_permission(session, "emp-007", SYSTEM_GRAFANA) == PERM_VIEWER
    assert ticket_status(session, "CHG-2004") != "Resolved"


def test_max_steps_does_not_close_ticket(session) -> None:
    run = start_run(
        session,
        actor_id=L1_ID,
        user_text="继续处理 INC-1008",
        case_id="max_steps",
        provider=provider_for_case("max_steps"),
    )
    session.flush()
    assert run.status == RUN_FAILED
    assert run.outcome_code == MAX_STEPS
    assert ticket_status(session, "INC-1008") == STATUS_INVESTIGATING
    assert "未关单" in (run.final_answer or "")


def test_demo_case_1_prints_clarify(capsys) -> None:
    from marlow.demo import main

    assert main(["--case", "1"]) == 0
    out = capsys.readouterr().out
    assert "clarify" in out
    assert "工单号" in out


def test_demo_subprocess_stdout_is_utf8() -> None:
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, "-m", "marlow.demo", "--case", "1"],
        check=True,
        capture_output=True,
    )
    text = proc.stdout.decode("utf-8")
    assert "请提供工单号" in text
    assert "clarify" in text
