"""Self-written Run loop. Does not UPDATE entitlements."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from marlow.actions import Action
from marlow.codes import (
    ACTION_ANSWER,
    ACTION_SKILL,
    ACTION_TOOL,
    APPROVAL_REJECTED,
    DECISION_APPROVE,
    DECISION_REJECT,
    FAKE_COST_CENTS_PER_STEP,
    FAKE_TOKENS_PER_STEP,
    MAX_COST_CENTS_LIMIT,
    MAX_STEPS,
    MAX_STEPS_LIMIT,
    MAX_TOKENS_LIMIT,
    MISSING_ARGUMENT,
    NON_RETRYABLE,
    NOT_ENOUGH_INFO,
    OK,
    RETRYABLE_TIMEOUT,
    RUN_ADMITTED,
    RUN_CANCELLED,
    RUN_COMPLETED,
    RUN_CREATED,
    RUN_FAILED,
    RUN_RUNNING,
    RUN_WAITING_APPROVAL,
    RUN_WAITING_TOOL,
    SKILL_VERSION,
    SOURCE_TRUST_INTERNAL_GATEWAY,
    STATUS_RESOLVED,
)
from marlow.evidence import assess_close_evidence
from marlow.fake import ActionProvider, StepFeedback
from marlow.faults import FAULT_TIMEOUT, FaultHooks
from marlow.llm import bind_provider, redact_secrets
from marlow.models import AgentSession, Approval, MemoryNote, Run, RunEvent, Ticket, TicketComment
from marlow.observation import Observation
from marlow.skills import apply_skill, match_skill
from marlow.tool_client import ToolClient, resolve_tool_client
from marlow.tools import TOOL_APPLY_ENTITLEMENT_CHANGE, TOOL_GET_ASSET

TICKET_ID_RE = re.compile(r"\b(INC-\d+|CHG-\d+)\b", re.IGNORECASE)
CLOSE_INTENT_RE = re.compile(r"关单|请关\s*(?:INC|CHG)-", re.IGNORECASE)

CLARIFY_ANSWER = "请提供工单号（如 INC-1001），当前信息不足，未改工单库。"
DEGRADE_ANSWER = "资产读取超时，已降级。未编造资产配置或关单。"
HITL_ANSWER = "权限变更草案已提交，等待管理员审批。"
APPROVE_RESUME_ANSWER = "审批已通过，权限已由网关写入。"
REJECT_RESUME_ANSWER = "变更被拒，这张工单未关单。权限未改。"
DENY_ANSWER = "变更未生效：网关拒绝。entitlements 未改。"
MAX_STEPS_ANSWER = "已达步数上限，安全停止，未关单。"
CANCEL_ANSWER = "任务已取消。"

OnEvent = Callable[[dict[str, Any]], None]
_ON_EVENT: ContextVar[OnEvent | None] = ContextVar("marlow_on_event", default=None)


@dataclass
class RunLimits:
    max_steps: int = MAX_STEPS_LIMIT
    max_tokens: int = MAX_TOKENS_LIMIT
    max_cost_cents: int = MAX_COST_CENTS_LIMIT


def requests_close(user_text: str) -> bool:
    """Operator asked to close. Investigate-only text must not match."""
    return bool(CLOSE_INTENT_RE.search(user_text or ""))


def extract_ticket_id(text: str) -> str | None:
    match = TICKET_ID_RE.search(text)
    if match is None:
        return None
    raw = match.group(1)
    prefix, _, rest = raw.partition("-")
    return f"{prefix.upper()}-{rest}"


# HTTP Fake is chosen only from the ticket id parsed out of user text.
# Client JSON/query case_id is ignored. Unlisted tickets stay investigate, never close_success.
_HTTP_FAKE_BY_TICKET: dict[str, str] = {
    "INC-1001": "close_success",
    "INC-1005": "timeout",
    "CHG-2004": "investigate",
}


def http_fake_case_id(user_text: str) -> str | None:
    """Map a parsed seed ticket to a Fake script. No ticket → None (clarify)."""
    ticket_id = extract_ticket_id(user_text)
    if ticket_id is None:
        return None
    if ticket_id == "CHG-2004" and "申请" in user_text:
        return "change_hitl"
    return _HTTP_FAKE_BY_TICKET.get(ticket_id, "investigate")


def http_fake_faults(user_text: str) -> FaultHooks:
    """Timeout seed needs the same in-process asset fault as CLI Fake case 3."""
    hooks = FaultHooks()
    if http_fake_case_id(user_text) == "timeout":
        hooks.set_target("get_asset", "ast-laptop-casey", FAULT_TIMEOUT)
    return hooks


def _new_id() -> str:
    return uuid.uuid4().hex


def _persist(session: Session) -> None:
    """Commit Run writes now. A crash can leave committed steps; terminal status + audit_events are the record."""
    session.commit()


def _set_status(session: Session, run: Run, status: str) -> None:
    run.status = status
    _emit(session, run, "state", status=status)


def _emit(session: Session, run: Run, event_kind: str, **payload: Any) -> None:
    blob = redact_secrets(json.dumps(payload, ensure_ascii=False))
    event = RunEvent(run_id=run.id, kind=event_kind, payload=blob)
    session.add(event)
    session.flush()
    event_id = event.id
    snapshot = {
        "id": event_id,
        "run_id": run.id,
        "kind": event.kind,
        "payload": event.payload,
        "request_id": run.request_id,
        "trace_id": run.trace_id,
        "status": run.status,
        "outcome_code": run.outcome_code,
        "final_answer": run.final_answer,
    }
    _persist(session)
    callback = _ON_EVENT.get()
    if callback is None:
        return
    callback(snapshot)


def _cancel_requested(session: Session, run: Run) -> bool:
    session.refresh(run, attribute_names=["cancel_requested"])
    return bool(run.cancel_requested)


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


def create_run(
    session: Session,
    *,
    actor_id: str,
    user_text: str,
    case_id: str | None = None,
    session_id: str | None = None,
) -> Run:
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
        cancel_requested=False,
    )
    session.add(run)
    session.flush()
    _emit(session, run, "state", status=RUN_CREATED)
    _set_status(session, run, RUN_ADMITTED)
    return run


def run_and_wait(
    session: Session,
    *,
    actor_id: str,
    user_text: str,
    case_id: str | None = None,
    session_id: str | None = None,
    faults: FaultHooks | None = None,
    provider: ActionProvider | None = None,
    limits: RunLimits | None = None,
    real: bool = False,
    llm_client: Any | None = None,
    tool_client: ToolClient | None = None,
) -> Run:
    """Synchronous Run for CLI. Web enqueues onto the worker instead."""
    return start_run(
        session,
        actor_id=actor_id,
        user_text=user_text,
        case_id=case_id,
        session_id=session_id,
        faults=faults,
        provider=provider,
        limits=limits,
        real=real,
        llm_client=llm_client,
        tool_client=tool_client,
    )


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
    real: bool = False,
    llm_client: Any | None = None,
    tool_client: ToolClient | None = None,
    run_id: str | None = None,
    on_event: OnEvent | None = None,
) -> Run:
    token = _ON_EVENT.set(on_event)
    try:
        return _start_run(
            session,
            actor_id=actor_id,
            user_text=user_text,
            case_id=case_id,
            session_id=session_id,
            faults=faults,
            provider=provider,
            limits=limits,
            real=real,
            llm_client=llm_client,
            tool_client=tool_client,
            run_id=run_id,
        )
    finally:
        _ON_EVENT.reset(token)


def _start_run(
    session: Session,
    *,
    actor_id: str,
    user_text: str,
    case_id: str | None = None,
    session_id: str | None = None,
    faults: FaultHooks | None = None,
    provider: ActionProvider | None = None,
    limits: RunLimits | None = None,
    real: bool = False,
    llm_client: Any | None = None,
    tool_client: ToolClient | None = None,
    run_id: str | None = None,
) -> Run:
    limits = limits or RunLimits()
    hooks = faults or FaultHooks()
    client = resolve_tool_client(session, hooks, tool_client)
    if run_id is not None:
        run = session.get(Run, run_id)
        if run is None:
            raise ValueError(f"run not found: {run_id}")
        actor_id = run.actor_id
        user_text = run.user_text
        if case_id is None:
            case_id = run.case_id
        ticket_id = run.ticket_id
        agent_session = session.get(AgentSession, run.session_id)
        if agent_session is None:
            raise ValueError(f"session not found: {run.session_id}")
    else:
        run = create_run(
            session,
            actor_id=actor_id,
            user_text=user_text,
            case_id=case_id,
            session_id=session_id,
        )
        ticket_id = run.ticket_id
        agent_session = session.get(AgentSession, run.session_id)
        if agent_session is None:
            raise ValueError("session not found")

    if _cancel_requested(session, run):
        _finish(session, run, agent_session, RUN_CANCELLED, RUN_CANCELLED, CANCEL_ANSWER, {})
        return run

    if ticket_id is None:
        _emit(session, run, "clarify", code=NOT_ENOUGH_INFO, message=CLARIFY_ANSWER)
        _finish(session, run, agent_session, RUN_COMPLETED, NOT_ENOUGH_INFO, CLARIFY_ANSWER, verified={})
        return run

    provider, llm_meta = bind_provider(
        user_text=user_text,
        case_id=case_id,
        real=real,
        provider=provider,
        client=llm_client,
    )
    if llm_meta.get("provider") == "openai":
        _emit(session, run, "llm", provider="openai", model=llm_meta.get("model", ""))

    verified: dict[str, Any] = {"ticket_id": ticket_id}
    _set_status(session, run, RUN_RUNNING)
    return _agent_loop(
        session,
        run,
        agent_session,
        actor_id=actor_id,
        ticket_id=ticket_id,
        provider=provider,
        client=client,
        limits=limits,
        verified=verified,
        feedback=None,
    )


def resume_run(
    session: Session,
    *,
    run_id: str,
    faults: FaultHooks | None = None,
    provider: ActionProvider | None = None,
    limits: RunLimits | None = None,
    real: bool = False,
    llm_client: Any | None = None,
    tool_client: ToolClient | None = None,
    on_event: OnEvent | None = None,
) -> Run:
    token = _ON_EVENT.set(on_event)
    try:
        return _resume_run(
            session,
            run_id=run_id,
            faults=faults,
            provider=provider,
            limits=limits,
            real=real,
            llm_client=llm_client,
            tool_client=tool_client,
        )
    finally:
        _ON_EVENT.reset(token)


def claim_run_resume(session: Session, run_id: str) -> bool:
    """UPDATE ... WHERE status=waiting_approval. Zero rows means another claim won."""
    result = session.execute(
        update(Run)
        .where(Run.id == run_id, Run.status == RUN_WAITING_APPROVAL)
        .values(status=RUN_RUNNING)
    )
    _persist(session)
    return int(result.rowcount or 0) == 1


def waiting_run_for_ticket(session: Session, ticket_id: str) -> Run | None:
    return session.scalar(
        select(Run)
        .where(Run.ticket_id == ticket_id, Run.status == RUN_WAITING_APPROVAL)
        .order_by(Run.id.desc())
    )


def latest_checkpoint(session: Session, run_id: str) -> dict[str, Any] | None:
    row = session.scalar(
        select(RunEvent)
        .where(RunEvent.run_id == run_id, RunEvent.kind == "checkpoint")
        .order_by(RunEvent.id.desc())
    )
    if row is None:
        return None
    try:
        data = json.loads(row.payload) if row.payload else {}
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _resume_run(
    session: Session,
    *,
    run_id: str,
    faults: FaultHooks | None,
    provider: ActionProvider | None,
    limits: RunLimits | None,
    real: bool,
    llm_client: Any | None,
    tool_client: ToolClient | None,
) -> Run:
    limits = limits or RunLimits()
    hooks = faults or FaultHooks()
    client = resolve_tool_client(session, hooks, tool_client)
    run = session.get(Run, run_id)
    if run is None:
        raise ValueError(f"run not found: {run_id}")
    actor_id = run.actor_id
    agent_session = session.get(AgentSession, run.session_id)
    if agent_session is None:
        raise ValueError(f"session not found: {run.session_id}")
    checkpoint = latest_checkpoint(session, run.id)
    if checkpoint is None:
        raise ValueError(f"checkpoint not found: {run_id}")

    run.step_count = int(checkpoint.get("step_count") or 0)
    run.token_used = int(checkpoint.get("token_used") or 0)
    run.cost_cents = int(checkpoint.get("cost_cents") or 0)
    verified = dict(checkpoint.get("verified") or {})
    ticket_id = str(checkpoint.get("ticket_id") or run.ticket_id or "")
    if not ticket_id:
        _finish(session, run, agent_session, RUN_FAILED, NOT_ENOUGH_INFO, CLARIFY_ANSWER, verified)
        return run

    if _cancel_requested(session, run):
        _finish(session, run, agent_session, RUN_CANCELLED, RUN_CANCELLED, CANCEL_ANSWER, verified)
        return run

    bound, llm_meta = bind_provider(
        user_text=run.user_text,
        case_id=run.case_id,
        real=real,
        provider=provider,
        client=llm_client,
    )
    bound.load_state(dict(checkpoint.get("provider") or {}))
    if llm_meta.get("provider") == "openai":
        _emit(session, run, "llm", provider="openai", model=llm_meta.get("model", ""), resumed=True)

    obs = _gateway_observation(session, run, checkpoint)
    last_raw = checkpoint.get("last_action") or {}
    last_action = Action(
        kind=str(last_raw.get("kind") or ACTION_SKILL),
        name=last_raw.get("name"),
        arguments=dict(last_raw.get("arguments") or {}),
        text=str(last_raw.get("text") or ""),
    )
    _emit(
        session,
        run,
        "observation",
        tool="approval_gateway",
        ok=obs.ok,
        code=obs.code,
        retryable=obs.retryable,
        source_trust=obs.source_trust,
    )
    if obs.code == APPROVAL_REJECTED:
        verified["skill_answer"] = REJECT_RESUME_ANSWER
    elif obs.ok:
        verified["skill_answer"] = APPROVE_RESUME_ANSWER
    feedback = StepFeedback(action=last_action, observation=obs, verified=dict(verified))
    if run.status != RUN_RUNNING:
        _set_status(session, run, RUN_RUNNING)
    return _agent_loop(
        session,
        run,
        agent_session,
        actor_id=actor_id,
        ticket_id=ticket_id,
        provider=bound,
        client=client,
        limits=limits,
        verified=verified,
        feedback=feedback,
    )


def _gateway_observation(session: Session, run: Run, checkpoint: dict[str, Any]) -> Observation:
    approval = session.scalar(select(Approval).where(Approval.run_id == run.id).order_by(Approval.id.desc()))
    if approval is None:
        return Observation(
            ok=False,
            code=NOT_ENOUGH_INFO,
            retryable=False,
            source_trust=SOURCE_TRUST_INTERNAL_GATEWAY,
            data={"reason": "missing_approval", "draft": checkpoint.get("draft") or {}},
        )
    approved = approval.status == "approved"
    return Observation(
        ok=approved,
        code=OK if approved else APPROVAL_REJECTED,
        retryable=False,
        source_trust=SOURCE_TRUST_INTERNAL_GATEWAY,
        data={
            "decision": DECISION_APPROVE if approved else DECISION_REJECT,
            "ticket_id": approval.ticket_id,
            "approval_status": approval.status,
            "draft": checkpoint.get("draft") or {},
        },
    )


def _pause_hitl(
    session: Session,
    run: Run,
    provider: ActionProvider,
    verified: dict[str, Any],
    action: Action,
    skill_result: Any,
) -> None:
    run.outcome_code = skill_result.code
    run.final_answer = skill_result.answer or HITL_ANSWER
    checkpoint = {
        "step_count": run.step_count,
        "token_used": run.token_used,
        "cost_cents": run.cost_cents,
        "verified": verified,
        "draft": skill_result.draft,
        "ticket_id": run.ticket_id,
        "actor_id": run.actor_id,
        "case_id": run.case_id,
        "provider": provider.dump_state(),
        "last_action": {
            "kind": action.kind,
            "name": action.name,
            "arguments": action.arguments,
            "text": action.text,
        },
    }
    _emit(session, run, "checkpoint", **checkpoint)
    _set_status(session, run, RUN_WAITING_APPROVAL)
    _emit(session, run, "hitl", code=skill_result.code, draft=skill_result.draft)


def _agent_loop(
    session: Session,
    run: Run,
    agent_session: AgentSession,
    *,
    actor_id: str,
    ticket_id: str,
    provider: ActionProvider,
    client: ToolClient,
    limits: RunLimits,
    verified: dict[str, Any],
    feedback: StepFeedback | None,
) -> Run:
    while True:
        if _cancel_requested(session, run):
            _finish(session, run, agent_session, RUN_CANCELLED, RUN_CANCELLED, CANCEL_ANSWER, verified)
            return run
        brake = _charge(run, limits)
        if brake:
            _emit(session, run, "brake", code=brake, steps=run.step_count)
            _finish(session, run, agent_session, RUN_FAILED, brake, MAX_STEPS_ANSWER, verified)
            return run
        _persist(session)

        action = provider.next_action(ticket_id, feedback)
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
            spec = match_skill(action.name, str(action.arguments.get("skill_version") or SKILL_VERSION))
            _emit(
                session,
                run,
                "skill",
                name=action.name,
                version=None if spec is None else spec.version,
                matched=spec is not None,
            )

            def run_tool(tool_action: Action) -> Observation:
                obs = _call_tool(session, run, actor_id, tool_action, client)
                if obs.ok:
                    _merge_verified(verified, tool_action.name or "", obs)
                return obs

            skill_result = apply_skill(
                session,
                actor_id=actor_id,
                name=action.name,
                arguments=action.arguments,
                ticket_id=ticket_id,
                run_tool=run_tool,
                assess_evidence=lambda payload: assess_close_evidence(provider, payload),
                reflect_rejections=int(verified.get("reflect_rejections") or 0),
            )
            verified.update(skill_result.verified_updates)
            if skill_result.answer:
                verified["skill_answer"] = skill_result.answer
            if skill_result.reflect:
                _emit(session, run, "reflect", **skill_result.reflect)
            if skill_result.notes_untrusted:
                _emit(
                    session,
                    run,
                    "memory",
                    untrusted=True,
                    notes=skill_result.notes_untrusted,
                )
            if skill_result.hitl:
                _pause_hitl(session, run, provider, verified, action, skill_result)
                return run
            if skill_result.finish:
                text = skill_result.answer or _answer_from_verified(verified)
                _finish(
                    session,
                    run,
                    agent_session,
                    RUN_COMPLETED,
                    skill_result.code,
                    text,
                    verified,
                )
                return run
            feedback = StepFeedback(
                action=action,
                skill_code=skill_result.code,
                skill_answer=skill_result.answer,
                notes_untrusted=list(skill_result.notes_untrusted),
                verified=dict(verified),
            )
            continue

        if action.kind != ACTION_TOOL or not action.name:
            _finish(session, run, agent_session, RUN_FAILED, "non_retryable", "未知 Action。", verified)
            return run

        obs = _call_tool(session, run, actor_id, action, client)
        if obs.code == MISSING_ARGUMENT:
            retries = int(verified.get("missing_arg_retries") or 0)
            if retries < 1:
                verified["missing_arg_retries"] = retries + 1
                feedback = StepFeedback(action=action, observation=obs, verified=dict(verified))
                continue
            _finish(
                session,
                run,
                agent_session,
                RUN_FAILED,
                NON_RETRYABLE,
                f"工具失败：{obs.code}。",
                verified,
            )
            return run

        if obs.retryable and obs.code == RETRYABLE_TIMEOUT:
            _emit(session, run, "retry", code=obs.code, tool=action.name)
            obs = _call_tool(session, run, actor_id, action, client)

        if action.name == TOOL_GET_ASSET and not obs.ok:
            _finish(session, run, agent_session, RUN_COMPLETED, obs.code, DEGRADE_ANSWER, verified)
            return run

        if action.name == TOOL_APPLY_ENTITLEMENT_CHANGE:
            _finish(
                session,
                run,
                agent_session,
                RUN_COMPLETED,
                obs.code,
                DENY_ANSWER if not obs.ok else "变更已由网关处理。",
                verified,
            )
            return run

        if obs.ok:
            _merge_verified(verified, action.name, obs)
            feedback = StepFeedback(action=action, observation=obs, verified=dict(verified))
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
    tool_client: ToolClient,
) -> Observation:
    _set_status(session, run, RUN_WAITING_TOOL)
    obs = tool_client.call(action.name or "", actor_id=actor_id, **action.arguments)
    _emit(
        session,
        run,
        "observation",
        tool=action.name,
        ok=obs.ok,
        code=obs.code,
        retryable=obs.retryable,
        source_trust=obs.source_trust,
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
    if verified.get("skill_answer"):
        return str(verified["skill_answer"])
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
    if (
        code == OK
        and requests_close(run.user_text or "")
        and run.ticket_id
        and ticket_status(session, run.ticket_id) != STATUS_RESOLVED
    ):
        code = NOT_ENOUGH_INFO
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
    _persist(session)


def comment_count(session: Session) -> int:
    return int(session.scalar(select(func.count()).select_from(TicketComment)) or 0)


def ticket_status(session: Session, ticket_id: str) -> str | None:
    row = session.get(Ticket, ticket_id)
    return None if row is None else row.status


def is_resolved(session: Session, ticket_id: str) -> bool:
    return ticket_status(session, ticket_id) == STATUS_RESOLVED
