"""CLI demo: print Run events. Fake only; no API Key."""

from __future__ import annotations

import argparse
import sys

from marlow.stdio import ensure_utf8_stdio

ensure_utf8_stdio()

from sqlalchemy import select
from sqlalchemy.orm import Session

from marlow.codes import DECISION_REJECT, PERM_EDITOR, SYSTEM_GRAFANA
from marlow.db import make_engine, prepare_database
from marlow.engine import start_run
from marlow.fake import provider_for_case
from marlow.faults import FAULT_TIMEOUT, FaultHooks
from marlow.gateway import apply_entitlement_change, entitlement_permission
from marlow.models import RunEvent
from marlow.seed import ADMIN_ID, L1_ID

DEMO_CASES: dict[int, dict[str, str]] = {
    1: {"case_id": "clarify", "text": "Grafana 登录有问题，帮我看看"},
    2: {"case_id": "close_success", "text": "请调查 INC-1001 并关单"},
    3: {"case_id": "timeout", "text": "读取 INC-1005 的资产配置"},
    4: {"case_id": "change_hitl", "text": "工单 CHG-2004 申请给 emp-007 加 Grafana Editor"},
    5: {"case_id": "l1_deny", "text": "在 CHG-2004 上直接改权限"},
}


def run_demo_case(session: Session, case: int) -> None:
    spec = DEMO_CASES[case]
    case_id = spec["case_id"]
    faults = FaultHooks()
    if case_id == "timeout":
        faults.set_target("get_asset", "ast-laptop-casey", FAULT_TIMEOUT)
    provider = None if case_id == "clarify" else provider_for_case(case_id)
    run = start_run(
        session,
        actor_id=L1_ID,
        user_text=spec["text"],
        case_id=case_id,
        faults=faults,
        provider=provider,
    )
    print(f"run_id={run.id} status={run.status} code={run.outcome_code}")
    print(f"answer={run.final_answer}")
    events = session.scalars(select(RunEvent).where(RunEvent.run_id == run.id).order_by(RunEvent.id))
    for event in events:
        print(f"event {event.kind} {event.payload}")
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


def main(argv: list[str] | None = None) -> int:
    ensure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Marlow Fake demo")
    parser.add_argument("--case", type=int, required=True, choices=sorted(DEMO_CASES))
    args = parser.parse_args(argv)
    engine = make_engine("sqlite:///:memory:")
    prepare_database(engine)
    with Session(engine) as session:
        run_demo_case(session, args.case)
        session.commit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
