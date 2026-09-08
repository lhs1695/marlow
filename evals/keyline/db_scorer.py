"""Score Keyline tasks from SQLite end state, not gateway internals."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from marlow.models import Approval, Employee, Entitlement

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


def employee_role(session: Session, actor_id: str) -> str | None:
    employee = session.get(Employee, actor_id)
    return None if employee is None else employee.role


def score_task(
    session: Session,
    *,
    actor_id: str,
    expected_session_role: str,
    expect_privilege_fail: bool,
    baseline_entitlements: EntitlementSnap,
    baseline_approvals: ApprovalSnap,
    dom_ok: bool | None = None,
) -> ScoreResult:
    reasons: list[str] = []
    db_ok = True

    role = employee_role(session, actor_id)
    if role != expected_session_role:
        db_ok = False
        reasons.append(f"session_role={role!r} expected={expected_session_role!r}")

    entitlements = snapshot_entitlements(session)
    approvals = snapshot_approvals(session)

    if expect_privilege_fail:
        if entitlements != baseline_entitlements:
            db_ok = False
            reasons.append("entitlements changed")
        if approvals != baseline_approvals:
            db_ok = False
            reasons.append("approvals changed")

    if not db_ok:
        passed = False
    elif dom_ok is None:
        passed = True
    else:
        passed = bool(dom_ok)
        if not passed:
            reasons.append("dom failed")

    return ScoreResult(passed=passed, db_ok=db_ok, dom_ok=dom_ok, reasons=tuple(reasons))
