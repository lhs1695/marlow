from __future__ import annotations

from sqlalchemy.orm import Session

from marlow.comments import add_ticket_comment as add_ticket_comment_fn
from marlow.gateway import apply_entitlement_change as apply_entitlement_change_fn
from marlow.observation import Observation


def add_ticket_comment(
    session: Session,
    *,
    actor_id: str,
    ticket_id: str,
    body: str,
) -> Observation:
    result = add_ticket_comment_fn(
        session,
        actor_id=actor_id,
        ticket_id=ticket_id,
        body=body,
    )
    return Observation(
        ok=result.ok,
        code=result.code,
        retryable=False,
        untrusted=True,
        data=None
        if not result.ok
        else {"comment_id": result.comment_id, "body": result.body},
    )


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
) -> Observation:
    result = apply_entitlement_change_fn(
        session,
        actor_id=actor_id,
        ticket_id=ticket_id,
        target_employee_id=target_employee_id,
        system=system,
        new_permission=new_permission,
        decision=decision,
        idempotency_key=idempotency_key,
    )
    return Observation(
        ok=result.ok,
        code=result.code,
        retryable=False,
        untrusted=True,
    )
