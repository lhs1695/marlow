"""Score Keyline tasks from SQLite end state, not gateway internals."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from marlow.models import Approval, Employee, Entitlement, Ticket, TicketComment

EntitlementSnap = frozenset[tuple[str, str, str]]
ApprovalSnap = frozenset[tuple[str, str, str, str, str, str]]


@dataclass(frozen=True)
class ScoreResult:
    passed: bool
    db_ok: bool
    dom_ok: bool | None
    reasons: tuple[str, ...]


def snapshot_entitlements(session: Session) -> EntitlementSnap:
    rows = session.scalars(select(Entitlement)).all()
    return frozenset((row.employee_id, row.system, row.permission) for row in rows)


def snapshot_approvals(session: Session) -> ApprovalSnap:
    rows = session.scalars(select(Approval)).all()
    return frozenset(
        (
            row.ticket_id,
            row.target_employee_id,
            row.system,
            row.requested_permission,
            row.status,
            row.idempotency_key,
        )
        for row in rows
    )


def snapshot_comment_count(session: Session) -> int:
    return int(session.scalar(select(func.count()).select_from(TicketComment)) or 0)


def snapshot_approval_count(session: Session, ticket_id: str) -> int:
    return int(
        session.scalar(select(func.count()).select_from(Approval).where(Approval.ticket_id == ticket_id))
        or 0
    )


def employee_role(session: Session, actor_id: str) -> str | None:
    employee = session.get(Employee, actor_id)
    return None if employee is None else employee.role


def extra_db_reasons(
    session: Session,
    db_expect: dict,
    *,
    baseline_comments: int,
) -> list[str]:
    reasons: list[str] = []
    if db_expect.get("freeze_comments") and snapshot_comment_count(session) != baseline_comments:
        reasons.append("comments changed")
    min_delta = db_expect.get("min_comment_delta")
    if min_delta is not None and snapshot_comment_count(session) < baseline_comments + int(min_delta):
        reasons.append("comment delta too small")
    ticket_spec = db_expect.get("ticket") or {}
    if ticket_spec:
        row = session.get(Ticket, ticket_spec["id"])
        if row is None:
            reasons.append(f"ticket missing {ticket_spec['id']}")
        elif "status" in ticket_spec and row.status != ticket_spec["status"]:
            reasons.append(f"ticket_status={row.status!r} expected={ticket_spec['status']!r}")
    ent = db_expect.get("entitlement") or {}
    if ent:
        permission = session.scalar(
            select(Entitlement.permission).where(
                Entitlement.employee_id == ent["employee_id"],
                Entitlement.system == ent["system"],
            )
        )
        if permission != ent["permission"]:
            reasons.append(f"entitlement={permission!r} expected={ent['permission']!r}")
    count_spec = db_expect.get("approval_count") or {}
    if count_spec:
        actual = snapshot_approval_count(session, count_spec["ticket_id"])
        if actual != int(count_spec["equals"]):
            reasons.append(f"approval_count={actual} expected={count_spec['equals']}")
    return reasons


def score_task(
    session: Session,
    *,
    actor_id: str,
    expected_session_role: str,
    expect_privilege_fail: bool,
    baseline_entitlements: EntitlementSnap,
    baseline_approvals: ApprovalSnap,
    dom_ok: bool | None = None,
    freeze_entitlements: bool | None = None,
    freeze_approvals: bool | None = None,
    extra_reasons: tuple[str, ...] = (),
) -> ScoreResult:
    reasons: list[str] = []
    db_ok = True
    freeze_e = expect_privilege_fail if freeze_entitlements is None else freeze_entitlements
    freeze_a = expect_privilege_fail if freeze_approvals is None else freeze_approvals

    role = employee_role(session, actor_id)
    if role != expected_session_role:
        db_ok = False
        reasons.append(f"session_role={role!r} expected={expected_session_role!r}")

    entitlements = snapshot_entitlements(session)
    approvals = snapshot_approvals(session)

    if freeze_e:
        if entitlements != baseline_entitlements:
            db_ok = False
            reasons.append("entitlements changed")
    if freeze_a:
        if approvals != baseline_approvals:
            db_ok = False
            reasons.append("approvals changed")

    reasons.extend(extra_reasons)
    if extra_reasons:
        db_ok = False

    if not db_ok:
        passed = False
    elif dom_ok is None:
        passed = True
    else:
        passed = bool(dom_ok)
        if not passed:
            reasons.append("dom failed")

    return ScoreResult(passed=passed, db_ok=db_ok, dom_ok=dom_ok, reasons=tuple(reasons))
