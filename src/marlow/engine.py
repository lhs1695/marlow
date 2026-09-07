"""Self-written Run loop. Does not UPDATE entitlements."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from marlow.actions import Action
from marlow.codes import (
    ACTION_ANSWER,
    ACTION_SKILL,
    ACTION_TOOL,
    APPROVAL_REQUIRED,
    FAKE_COST_CENTS_PER_STEP,
    FAKE_TOKENS_PER_STEP,
    MAX_COST_CENTS_LIMIT,
    MAX_STEPS,
    MAX_STEPS_LIMIT,
    MAX_TOKENS_LIMIT,
    NOT_ENOUGH_INFO,
    RETRYABLE_TIMEOUT,
    RUN_ADMITTED,
    RUN_COMPLETED,
    RUN_CREATED,
    RUN_FAILED,
    RUN_RUNNING,
    RUN_WAITING_APPROVAL,
    RUN_WAITING_TOOL,
    SKILL_ENTITLEMENT_CHANGE,
    STATUS_RESOLVED,
    UNAUTHORIZED,
)
from marlow.fake import ActionProvider, provider_for_case
from marlow.faults import FaultHooks
from marlow.models import AgentSession, MemoryNote, Run, RunEvent, Ticket, TicketComment
from marlow.observation import Observation
from marlow.tools import TOOL_APPLY_ENTITLEMENT_CHANGE, TOOL_GET_ASSET, execute_tool

TICKET_ID_RE = re.compile(r"\b(INC-\d+|CHG-\d+)\b", re.IGNORECASE)

CLARIFY_ANSWER = "请提供工单号（如 INC-1001），当前信息不足，未改工单库。"
DEGRADE_ANSWER = "资产读取超时，已降级。未编造资产配置或关单。"
HITL_ANSWER = "权限变更草案已提交，等待管理员审批。本 Run 不续跑。"
DENY_ANSWER = "变更未生效：网关拒绝。entitlements 未改。"
MAX_STEPS_ANSWER = "已达步数上限，安全停止，未关单。"


@dataclass
class RunLimits:
    max_steps: int = MAX_STEPS_LIMIT
    max_tokens: int = MAX_TOKENS_LIMIT
    max_cost_cents: int = MAX_COST_CENTS_LIMIT


def extract_ticket_id(text: str) -> str | None:
    match = TICKET_ID_RE.search(text)
    if match is None:
        return None
    raw = match.group(1)
    prefix, _, rest = raw.partition("-")
    return f"{prefix.upper()}-{rest}"


def _new_id() -> str:
    return uuid.uuid4().hex


def _set_status(session: Session, run: Run, status: str) -> None:
    run.status = status
    _emit(session, run, "state", status=status)


def _emit(session: Session, run: Run, event_kind: str, **payload: Any) -> None:
    session.add(RunEvent(run_id=run.id, kind=event_kind, payload=json.dumps(payload, ensure_ascii=False)))


def _charge(run: Run, limits: RunLimits) -> str | None:
    run.step_count += 1
    run.token_used += FAKE_TOKENS_PER_STEP
    run.cost_cents += FAKE_COST_CENTS_PER_STEP
    if run.step_count > limits.max_steps:
        return MAX_STEPS
    if run.token_used > limits.max_tokens:
        return MAX_STEPS
    if run.cost_cents > limits.max_cost_cents:
        return MAX_STEPS
    return None


def start_run(
    session: Session,
    *,
    actor_id: str,
    user_text: str,
    case_id: str | None = None,
    session_id: str | None = None,
    faults: FaultHooks | None = None,
    provider: ActionProvider | None = None,
    limits: RunLimits | None = None,
) -> Run:
    limits = limits or RunLimits()
    hooks = faults or FaultHooks()
    ticket_id = extract_ticket_id(user_text)
    agent_session = _session(session, session_id=session_id, actor_id=actor_id)
    run_id = _new_id()
    run = Run(
        id=run_id,
        session_id=agent_session.id,
        request_id=run_id,
        trace_id=_new_id(),
        actor_id=actor_id,
        case_id=case_id,
        user_text=user_text,
        status=RUN_CREATED,
        ticket_id=ticket_id,
    )
    session.add(run)
    session.flush()
    _emit(session, run, "state", status=RUN_CREATED)
    _set_status(session, run, RUN_ADMITTED)

    if ticket_id is None:
        _emit(session, run, "clarify", code=NOT_ENOUGH_INFO, message=CLARIFY_ANSWER)
        _finish(session, run, agent_session, RUN_COMPLETED, NOT_ENOUGH_INFO, CLARIFY_ANSWER, verified={})
        return run

    if provider is None:
        if not case_id:
            raise ValueError("case_id or provider is required")
        provider = provider_for_case(case_id)

    verified: dict[str, Any] = {"ticket_id": ticket_id}
    _set_status(session, run, RUN_RUNNING)

    while True:
        brake = _charge(run, limits)
        if brake:
            _emit(session, run, "brake", code=brake, steps=run.step_count)
            _finish(session, run, agent_session, RUN_FAILED, brake, MAX_STEPS_ANSWER, verified)
            return run

        action = provider.next_action(ticket_id)
        _emit(
            session,
            run,
            "action",
            action_kind=action.kind,
            name=action.name,
            arguments=action.arguments,
        )

        if action.kind == ACTION_ANSWER:
            text = _answer_from_verified(verified)
            _finish(session, run, agent_session, RUN_COMPLETED, "ok", text, verified)
            return run

        if action.kind == ACTION_SKILL:
            if action.name == SKILL_ENTITLEMENT_CHANGE:
                _set_status(session, run, RUN_WAITING_APPROVAL)
                _emit(session, run, "hitl", code=APPROVAL_REQUIRED, draft=action.arguments)
                _finish(
                    session,
                    run,
                    agent_session,
                    RUN_COMPLETED,
                    APPROVAL_REQUIRED,
                    HITL_ANSWER,
                    verified,
                )
                return run
            text = _answer_from_verified(verified)
            _finish(session, run, agent_session, RUN_COMPLETED, "ok", text, verified)
            return run

        if action.kind != ACTION_TOOL or not action.name:
            _finish(session, run, agent_session, RUN_FAILED, "non_retryable", "未知 Action。", verified)
            return run

        obs = _call_tool(session, run, actor_id, action, hooks)
        if obs.retryable and obs.code == RETRYABLE_TIMEOUT:
            _emit(session, run, "retry", code=obs.code, tool=action.name)
            obs = _call_tool(session, run, actor_id, action, hooks)

        if action.name == TOOL_GET_ASSET and not obs.ok:
            _finish(session, run, agent_session, RUN_COMPLETED, obs.code, DEGRADE_ANSWER, verified)
            return run

        if action.name == TOOL_APPLY_ENTITLEMENT_CHANGE:
            _finish(session, run, agent_session, RUN_COMPLETED, obs.code, DENY_ANSWER if not obs.ok else "变更已由网关处理。", verified)
            return run

        if obs.ok:
            _merge_verified(verified, action.name, obs)
            continue

        if not obs.retryable:
            _finish(session, run, agent_session, RUN_FAILED, obs.code, f"工具失败：{obs.code}。", verified)
            return run

        _finish(session, run, agent_session, RUN_COMPLETED, obs.code, DEGRADE_ANSWER, verified)
        return run


def _call_tool(
    session: Session,
    run: Run,
    actor_id: str,
    action: Action,
    hooks: FaultHooks,
) -> Observation:
    _set_status(session, run, RUN_WAITING_TOOL)
    obs = execute_tool(session, action.name or "", actor_id=actor_id, faults=hooks, **action.arguments)
    _emit(
        session,
        run,
        "observation",
        tool=action.name,
        ok=obs.ok,
        code=obs.code,
        retryable=obs.retryable,
        untrusted=obs.untrusted,
    )
    _set_status(session, run, RUN_RUNNING)
    return obs


def _merge_verified(verified: dict[str, Any], tool_name: str, obs: Observation) -> None:
    data = obs.data or {}
    if tool_name == "get_ticket" and "ticket" in data:
        ticket = data["ticket"]
        verified["ticket_id"] = ticket.get("id")
        verified["ticket_status"] = ticket.get("status")
        verified["requester_id"] = ticket.get("requester_id")
        verified["asset_id"] = ticket.get("asset_id")
        if ticket.get("kb_doc_id"):
            verified["kb_doc_id"] = ticket["kb_doc_id"]
        if ticket.get("kb_version"):
            verified["kb_version"] = ticket["kb_version"]
    if tool_name == "search_kb":
        hits = data.get("hits") or []
        if hits:
            verified["kb_doc_id"] = hits[0].get("doc_id")
            verified["kb_version"] = hits[0].get("version")
    if tool_name == "get_asset" and "asset" in data:
        verified["asset"] = {
            "id": data["asset"].get("id"),
            "owner_employee_id": data["asset"].get("owner_employee_id"),
        }


def _answer_from_verified(verified: dict[str, Any]) -> str:
    parts = ["已用已验证上下文作答。"]
    if verified.get("ticket_id"):
        parts.append(f"ticket_id={verified['ticket_id']}")
    if verified.get("ticket_status"):
        parts.append(f"status={verified['ticket_status']}")
    if verified.get("kb_doc_id") and verified.get("kb_version"):
        parts.append(f"kb={verified['kb_doc_id']}@{verified['kb_version']}")
    return " ".join(parts)


def _session(session: Session, *, session_id: str | None, actor_id: str) -> AgentSession:
    if session_id:
        existing = session.get(AgentSession, session_id)
        if existing is not None:
            return existing
    row = AgentSession(id=session_id or _new_id(), actor_id=actor_id, summary="")
    session.add(row)
    session.flush()
    return row


def _finish(
    session: Session,
    run: Run,
    agent_session: AgentSession,
    status: str,
    code: str,
    answer: str,
    verified: dict[str, Any],
) -> None:
    run.outcome_code = code
    run.final_answer = answer
    _set_status(session, run, status)
    _emit(session, run, "answer", code=code, text=answer)
    agent_session.summary = f"{run.case_id or 'run'} {code} ticket={run.ticket_id or '-'}"
    requester_id = verified.get("requester_id")
    asset_id = verified.get("asset_id")
    if requester_id or asset_id:
        session.add(
            MemoryNote(
                requester_id=requester_id,
                asset_id=asset_id,
                run_id=run.id,
                body=f"untrusted note from run {run.id}: {code}",
            )
        )


def comment_count(session: Session) -> int:
    return int(session.scalar(select(func.count()).select_from(TicketComment)) or 0)


def ticket_status(session: Session, ticket_id: str) -> str | None:
    row = session.get(Ticket, ticket_id)
    return None if row is None else row.status


def is_resolved(session: Session, ticket_id: str) -> bool:
    return ticket_status(session, ticket_id) == STATUS_RESOLVED
