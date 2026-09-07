from sqlalchemy import func, select

from marlow.codes import (
    APPROVAL_REJECTED,
    DECISION_APPROVE,
    DECISION_REJECT,
    IDEMPOTENT_REPLAY,
    PERM_EDITOR,
    PERM_VIEWER,
    STATUS_REJECTED,
    STATUS_RESOLVED,
    SYSTEM_GRAFANA,
    TICKET_NOT_FOUND,
    UNAUTHORIZED,
)
from marlow.gateway import apply_entitlement_change, entitlement_permission
from marlow.models import Approval, AuditEvent, Entitlement, Ticket
from marlow.seed import ADMIN_ID, L1_ID


def _apply(session, *, actor_id: str, ticket_id: str, target: str, key: str, decision: str):
    return apply_entitlement_change(
        session,
        actor_id=actor_id,
        ticket_id=ticket_id,
        target_employee_id=target,
        system=SYSTEM_GRAFANA,
        new_permission=PERM_EDITOR,
        decision=decision,
        idempotency_key=key,
    )


def test_l1_change_denied_entitlements_unchanged_and_audit_deny(session) -> None:
    before = entitlement_permission(session, "emp-007", SYSTEM_GRAFANA)
    assert before == PERM_VIEWER
    entitlement_count = session.scalar(select(func.count()).select_from(Entitlement))

    result = _apply(
        session,
        actor_id=L1_ID,
        ticket_id="CHG-2004",
        target="emp-007",
        key="k-l1-deny",
        decision=DECISION_APPROVE,
    )
    session.flush()

    assert result.ok is False
    assert result.code == UNAUTHORIZED
    assert entitlement_permission(session, "emp-007", SYSTEM_GRAFANA) == PERM_VIEWER
    assert session.scalar(select(func.count()).select_from(Entitlement)) == entitlement_count
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
    assert session.scalar(select(Approval).where(Approval.idempotency_key == "k-l1-deny")) is None


def test_admin_reject_leaves_entitlement_and_rejects_ticket(session) -> None:
    result = _apply(
        session,
        actor_id=ADMIN_ID,
        ticket_id="CHG-2003",
        target="emp-006",
        key="k-admin-reject",
        decision=DECISION_REJECT,
    )
    session.flush()

    assert result.ok is True
    assert result.code == APPROVAL_REJECTED
    assert entitlement_permission(session, "emp-006", SYSTEM_GRAFANA) == PERM_VIEWER
    ticket = session.get(Ticket, "CHG-2003")
    assert ticket is not None
    assert ticket.status == STATUS_REJECTED


def test_admin_approve_changes_entitlement_row(session) -> None:
    result = _apply(
        session,
        actor_id=ADMIN_ID,
        ticket_id="CHG-2004",
        target="emp-007",
        key="k-admin-approve",
        decision=DECISION_APPROVE,
    )
    session.flush()

    assert result.ok is True
    assert entitlement_permission(session, "emp-007", SYSTEM_GRAFANA) == PERM_EDITOR
    ticket = session.get(Ticket, "CHG-2004")
    assert ticket is not None
    assert ticket.status == STATUS_RESOLVED
    approval = session.scalar(select(Approval).where(Approval.idempotency_key == "k-admin-approve"))
    assert approval is not None
    assert approval.status == "approved"


def test_repeat_same_idempotency_key_does_not_double_write(session) -> None:
    first = _apply(
        session,
        actor_id=ADMIN_ID,
        ticket_id="CHG-2004",
        target="emp-007",
        key="k-idem",
        decision=DECISION_APPROVE,
    )
    session.flush()
    approval_count = session.scalar(select(func.count()).select_from(Approval))
    entitlement_count = session.scalar(select(func.count()).select_from(Entitlement))

    second = _apply(
        session,
        actor_id=ADMIN_ID,
        ticket_id="CHG-2004",
        target="emp-007",
        key="k-idem",
        decision=DECISION_APPROVE,
    )
    session.flush()

    assert first.code != IDEMPOTENT_REPLAY
    assert second.code == IDEMPOTENT_REPLAY
    assert entitlement_permission(session, "emp-007", SYSTEM_GRAFANA) == PERM_EDITOR
    assert session.scalar(select(func.count()).select_from(Approval)) == approval_count
    assert session.scalar(select(func.count()).select_from(Entitlement)) == entitlement_count


def test_missing_ticket_does_not_insert_business_rows(session) -> None:
    tickets = session.scalar(select(func.count()).select_from(Ticket))
    approvals = session.scalar(select(func.count()).select_from(Approval))
    entitlements = session.scalar(select(func.count()).select_from(Entitlement))

    result = _apply(
        session,
        actor_id=ADMIN_ID,
        ticket_id="INC-9999",
        target="emp-007",
        key="k-missing",
        decision=DECISION_APPROVE,
    )
    session.flush()

    assert result.ok is False
    assert result.code == TICKET_NOT_FOUND
    assert session.scalar(select(func.count()).select_from(Ticket)) == tickets
    assert session.scalar(select(func.count()).select_from(Approval)) == approvals
    assert session.scalar(select(func.count()).select_from(Entitlement)) == entitlements
    assert session.get(Ticket, "INC-9999") is None
