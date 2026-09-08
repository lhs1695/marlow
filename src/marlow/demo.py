"""CLI demo: print Run events. Fake by default; --real uses OpenAI if a Key is set."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

from marlow.stdio import ensure_utf8_stdio

ensure_utf8_stdio()

from sqlalchemy import select
from sqlalchemy.orm import Session

from marlow.codes import DECISION_REJECT, PERM_EDITOR, SYSTEM_GRAFANA
from marlow.db import make_engine, prepare_database
from marlow.engine import start_run, ticket_status
from marlow.faults import FAULT_TIMEOUT, FaultHooks
from marlow.gateway import apply_entitlement_change, entitlement_permission
from marlow.llm import has_api_key, redact_secrets, write_live_report
from marlow.models import RunEvent
from marlow.seed import ADMIN_ID, L1_ID

DEMO_CASES: dict[int, dict[str, str]] = {
    1: {"case_id": "clarify", "text": "Grafana 登录有问题，帮我看看"},
    2: {"case_id": "close_success", "text": "请调查 INC-1001 并关单"},
    3: {"case_id": "timeout", "text": "读取 INC-1005 的资产配置"},
    4: {"case_id": "change_hitl", "text": "工单 CHG-2004 申请给 emp-007 加 Grafana Editor"},
    5: {"case_id": "l1_deny", "text": "在 CHG-2004 上直接改权限"},
}


def run_demo_case(session: Session, case: int, *, real: bool = False) -> dict[str, Any] | None:
    spec = DEMO_CASES[case]
    case_id = spec["case_id"]
    faults = FaultHooks()
    if case_id == "timeout":
        faults.set_target("get_asset", "ast-laptop-casey", FAULT_TIMEOUT)
    used_openai = bool(real and has_api_key())
    if real and not has_api_key():
        print("provider=fake fallback=missing_api_key")
    elif used_openai:
        print("provider=openai")
    else:
        print("provider=fake")
    run = start_run(
        session,
        actor_id=L1_ID,
        user_text=spec["text"],
        case_id=case_id,
        faults=faults,
        real=real,
    )
    print(f"run_id={run.id} status={run.status} code={run.outcome_code}")
    print(f"answer={redact_secrets(run.final_answer or '')}")
    events = session.scalars(select(RunEvent).where(RunEvent.run_id == run.id).order_by(RunEvent.id))
    for event in events:
        print(f"event {event.kind} {redact_secrets(event.payload)}")
    if case == 2:
        print(f"ticket_status={ticket_status(session, 'INC-1001')}")
    if case == 4:
        result = apply_entitlement_change(
            session,
            actor_id=ADMIN_ID,
            ticket_id="CHG-2003",
            target_employee_id="emp-006",
            system=SYSTEM_GRAFANA,
            new_permission=PERM_EDITOR,
            decision=DECISION_REJECT,
            idempotency_key="demo-case4-reject",
        )
        after = entitlement_permission(session, "emp-006", SYSTEM_GRAFANA)
        print(f"admin_reject code={result.code} emp-006={after}")
    if not used_openai:
        return None
    return {
        "date": dt.date.today().isoformat(),
        "model": _model_from_events(session, run.id),
        "case": case,
        "case_id": case_id,
        "outcome_code": run.outcome_code,
        "status": run.status,
        "ticket_id": run.ticket_id,
        "ticket_status": ticket_status(session, run.ticket_id) if run.ticket_id else None,
        "final_answer": run.final_answer,
    }


def _model_from_events(session: Session, run_id: str) -> str:
    rows = session.scalars(select(RunEvent).where(RunEvent.run_id == run_id, RunEvent.kind == "llm"))
    for row in rows:
        try:
            payload = json.loads(row.payload)
        except json.JSONDecodeError:
            continue
        if payload.get("model"):
            return str(payload["model"])
    return ""


def main(argv: list[str] | None = None) -> int:
    ensure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Marlow demo (Fake default; --real for OpenAI)")
    parser.add_argument("--case", type=int, required=True, choices=sorted(DEMO_CASES))
    parser.add_argument("--real", action="store_true", help="Use OpenAI-compatible chat if OPENAI_API_KEY is set")
    parser.add_argument(
        "--report",
        type=Path,
        help="Write a live-model report JSON (gitignored). Not used in CI.",
    )
    args = parser.parse_args(argv)
    engine = make_engine("sqlite:///:memory:")
    prepare_database(engine)
    with Session(engine) as session:
        report = run_demo_case(session, args.case, real=args.real)
        session.commit()
        if args.report and report is not None:
            write_live_report(args.report, report)
            print(f"report={args.report}")
        elif args.report and report is None:
            print("report skipped (not a live OpenAI run)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
