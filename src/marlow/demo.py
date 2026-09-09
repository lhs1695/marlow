"""CLI demo: print Run events. Fake by default; --real uses OpenAI if a Key is set."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from marlow.credentials import load_local_env
from marlow.stdio import ensure_utf8_stdio

ensure_utf8_stdio()

from sqlalchemy import select
from sqlalchemy.orm import Session

from marlow.codes import DECISION_REJECT, PERM_EDITOR, SYSTEM_GRAFANA
from marlow.db import make_engine, prepare_database
from marlow.engine import start_run, ticket_status
from marlow.faults import FAULT_TIMEOUT, FaultHooks
from marlow.gateway import apply_entitlement_change, entitlement_permission
from marlow.live import live_run_record
from marlow.llm import OpenAIActionProvider, has_api_key, redact_secrets, write_live_report
from marlow.models import RunEvent
from marlow.seed import ADMIN_ID, L1_ID

DEMO_CASES: dict[int, dict[str, str]] = {
    1: {"case_id": "clarify", "text": "Grafana 登录有问题，帮我看看"},
    2: {"case_id": "close_success", "text": "请调查 INC-1001 并关单"},
    3: {"case_id": "timeout", "text": "读取 INC-1005 的资产配置"},
    4: {"case_id": "change_hitl", "text": "工单 CHG-2004 申请给 emp-007 加 Grafana Editor"},
    5: {"case_id": "l1_deny", "text": "在 CHG-2004 上直接改权限"},
}

_EVENT_KEYS = ("code", "ticket_id", "skill", "name", "tool", "outcome", "status")


def _event_line(kind: str, payload: str) -> str:
    raw = redact_secrets(payload)
    try:
        data = json.loads(payload) if payload else {}
    except json.JSONDecodeError:
        return f"{kind}\t{raw}"
    if not isinstance(data, dict):
        return f"{kind}\t{raw}"
    parts = [kind]
    for key in _EVENT_KEYS:
        value = data.get(key)
        if value not in (None, ""):
            parts.append(f"{key}={value}")
    return "\t".join(str(part) for part in parts)


def run_demo_case(
    session: Session,
    case: int,
    *,
    real: bool = False,
    llm_client: Any | None = None,
    verbose: bool = True,
) -> dict[str, Any] | None:
    spec = DEMO_CASES[case]
    case_id = spec["case_id"]
    faults = FaultHooks()
    if case_id == "timeout":
        faults.set_target("get_asset", "ast-laptop-casey", FAULT_TIMEOUT)
    used_openai = bool(real and (llm_client is not None or has_api_key()))
    if verbose:
        if real and not used_openai:
            print("provider=fake fallback=missing_api_key")
        elif used_openai:
            print("provider=openai")
        else:
            print("provider=fake")
    provider = OpenAIActionProvider(spec["text"], client=llm_client) if used_openai else None
    started = time.perf_counter()
    run = start_run(
        session,
        actor_id=L1_ID,
        user_text=spec["text"],
        case_id=case_id,
        faults=faults,
        provider=provider,
        real=real,
        llm_client=None if provider is not None else llm_client,
    )
    latency_ms = (time.perf_counter() - started) * 1000.0
    if verbose:
        print(f"run_id={run.id} status={run.status} code={run.outcome_code}")
        print(f"answer={redact_secrets(run.final_answer or '')}")
        print("kind\tfields")
        events = session.scalars(select(RunEvent).where(RunEvent.run_id == run.id).order_by(RunEvent.id))
        for event in events:
            print(_event_line(event.kind, event.payload))
        if case == 2:
            print(f"ticket_status={ticket_status(session, 'INC-1001')}")
    extra: dict[str, Any] = {}
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
        extra = {"admin_reject_code": result.code, "emp-006": after}
        if verbose:
            print(f"admin_reject code={result.code} ticket=CHG-2003 emp-006={after}")
            print("reject path=CHG-2003/emp-006 (entitlements stay Viewer)")
            print("approve path=CHG-2004/emp-007 — admin clicks /approvals; this CLI does not approve")
    if not used_openai:
        return None
    return live_run_record(
        session,
        case=case,
        case_id=case_id,
        run=run,
        latency_ms=latency_ms,
        provider=provider,
        extra=extra,
    )


def main(argv: list[str] | None = None) -> int:
    ensure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Marlow demo (Fake default; --real for OpenAI)")
    parser.add_argument("--case", type=int, required=True, choices=sorted(DEMO_CASES))
    parser.add_argument(
        "--real",
        action="store_true",
        help="Use OpenAI-compatible chat if XAI_API_KEY or OPENAI_API_KEY is set",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="Write one live run JSON (no p50). For n=10 p50/p95 use python -m marlow.live.",
    )
    args = parser.parse_args(argv)
    load_local_env()
    engine = make_engine("sqlite:///:memory:")
    prepare_database(engine)
    with Session(engine) as session:
        report = run_demo_case(session, args.case, real=args.real)
        session.commit()
        if args.report and report is not None:
            write_live_report(args.report, report)
            print(f"report={args.report}")
            print("p50/p95: python -m marlow.live")
        elif args.report and report is None:
            print("report skipped (not a live OpenAI run)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
