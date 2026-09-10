"""Approval gateway: the only runtime writer of entitlements."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from marlow.codes import (
    APPROVAL_REJECTED,
    DECISION_APPROVE,
    DECISION_REJECT,
    IDEMPOTENT_REPLAY,
    OK,
    ROLE_ADMIN,
    ROLE_L1,
    STATUS_REJECTED,
    STATUS_RESOLVED,
    TICKET_NOT_FOUND,
    UNAUTHORIZED,
)
from marlow.models import Approval, AuditEvent, Employee, Entitlement, Ticket

ACTION = "apply_entitlement_change"


@dataclass(frozen=True)
class ApplyResult:
    ok: bool
    code: str


def apply_entitlement_change(
    session: Session,
    *,
    actor_id: str,
    ticket_id: str,
    target_employee_id: str,
    system: str,
    new_permission: str,
    decision: str,
    idempotency_key: str,
    run_id: str | None = None,
) -> ApplyResult:
    actor = session.get(Employee, actor_id)
    actor_role = actor.role if actor is not None else "unknown"

    if actor is None or actor.role == ROLE_L1 or actor.role != ROLE_ADMIN:
        _audit(
            session,
            actor_id=actor_id,
            actor_role=actor_role,
            ticket_id=ticket_id,
            outcome="deny",
            detail=UNAUTHORIZED,
        )
        return ApplyResult(ok=False, code=UNAUTHORIZED)

    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        _audit(
            session,
            actor_id=actor_id,
            actor_role=actor_role,
            ticket_id=ticket_id,
            outcome="deny",
            detail=TICKET_NOT_FOUND,
        )
        return ApplyResult(ok=False, code=TICKET_NOT_FOUND)

    existing = session.scalar(select(Approval).where(Approval.idempotency_key == idempotency_key))
    if existing is not None:
        _audit(
            session,
            actor_id=actor_id,
            actor_role=actor_role,
            ticket_id=ticket_id,
            outcome="replay",
            detail=IDEMPOTENT_REPLAY,
        )
        return ApplyResult(ok=True, code=IDEMPOTENT_REPLAY)

    if decision == DECISION_REJECT:
        session.add(
            Approval(
                ticket_id=ticket_id,
                run_id=run_id,
                target_employee_id=target_employee_id,
                system=system,
                requested_permission=new_permission,
                status="rejected",
                idempotency_key=idempotency_key,
                decided_by_id=actor_id,
            )
        )
        ticket.status = STATUS_REJECTED
        _audit(
            session,
            actor_id=actor_id,
            actor_role=actor_role,
            ticket_id=ticket_id,
            outcome="rejected",
            detail=APPROVAL_REJECTED,
        )
        return ApplyResult(ok=True, code=APPROVAL_REJECTED)

    if decision != DECISION_APPROVE:
        _audit(
            session,
            actor_id=actor_id,
            actor_role=actor_role,
            ticket_id=ticket_id,
            outcome="deny",
            detail=UNAUTHORIZED,
        )
        return ApplyResult(ok=False, code=UNAUTHORIZED)

    _set_entitlement_permission(
        session,
        employee_id=target_employee_id,
        system=system,
        permission=new_permission,
    )
    session.add(
        Approval(
            ticket_id=ticket_id,
            run_id=run_id,
            target_employee_id=target_employee_id,
            system=system,
            requested_permission=new_permission,
            status="approved",
            idempotency_key=idempotency_key,
            decided_by_id=actor_id,
        )
    )
    ticket.status = STATUS_RESOLVED
    _audit(
        session,
        actor_id=actor_id,
        actor_role=actor_role,
        ticket_id=ticket_id,
        outcome="approved",
        detail=OK,
    )
    return ApplyResult(ok=True, code=OK)


def _set_entitlement_permission(
    session: Session,
    *,
    employee_id: str,
    system: str,
    permission: str,
) -> None:
    """Sole UPDATE path for entitlements rows."""
    row = session.scalar(
        select(Entitlement).where(
            Entitlement.employee_id == employee_id,
            Entitlement.system == system,
        )
    )
    if row is None:
        session.add(
            Entitlement(employee_id=employee_id, system=system, permission=permission)
        )
        return
    row.permission = permission


def _audit(
    session: Session,
    *,
    actor_id: str,
    actor_role: str,
    ticket_id: str,
    outcome: str,
    detail: str,
) -> None:
    session.add(
        AuditEvent(
            actor_id=actor_id,
            actor_role=actor_role,
            action=ACTION,
            ticket_id=ticket_id,
            outcome=outcome,
            detail=detail,
        )
    )


def entitlement_permission(session: Session, employee_id: str, system: str) -> str | None:
    row = session.scalar(
        select(Entitlement).where(
            Entitlement.employee_id == employee_id,
            Entitlement.system == system,
        )
    )
    return None if row is None else row.permission


def count_table(session: Session, model: type[object]) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)
