from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from marlow.codes import (
    QUEUE_CHANGE,
    QUEUE_L1,
    ROLE_ADMIN,
    ROLE_L1,
    TICKET_NOT_FOUND,
    UNAUTHORIZED,
)
from marlow.models import Employee, Ticket, TicketComment
from marlow.observation import Observation


def visible_queues(role: str) -> frozenset[str] | None:
    if role == ROLE_L1:
        return frozenset({QUEUE_L1})
    if role == ROLE_ADMIN:
        return frozenset({QUEUE_L1, QUEUE_CHANGE})
    return None


def _actor_or_deny(session: Session, actor_id: str) -> tuple[Employee | None, Observation | None]:
    actor = session.get(Employee, actor_id)
    if actor is None or visible_queues(actor.role) is None:
        return None, Observation(ok=False, code=UNAUTHORIZED, retryable=False)
    return actor, None


def get_ticket(session: Session, *, actor_id: str, ticket_id: str) -> Observation:
    actor, deny = _actor_or_deny(session, actor_id)
    if deny is not None:
        return deny
    assert actor is not None
    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        return Observation(
            ok=False,
            code=TICKET_NOT_FOUND,
            retryable=False,
        )
    queues = visible_queues(actor.role)
    assert queues is not None
    if ticket.queue not in queues:
        return Observation(ok=False, code=UNAUTHORIZED, retryable=False)
    comments = list(
        session.scalars(select(TicketComment).where(TicketComment.ticket_id == ticket.id))
    )
    return Observation(
        ok=True,
        code="ok",
        retryable=False,
        data={
            "ticket": {
                "id": ticket.id,
                "title": ticket.title,
                "description": ticket.description,
                "status": ticket.status,
                "queue": ticket.queue,
                "requester_id": ticket.requester_id,
                "asset_id": ticket.asset_id,
                "priority": ticket.priority,
                "kb_doc_id": ticket.kb_doc_id,
                "kb_version": ticket.kb_version,
            },
            "comments": [
                {"id": c.id, "author_id": c.author_id, "body": c.body} for c in comments
            ],
        },
    )


def search_tickets(
    session: Session,
    *,
    actor_id: str,
    query: str = "",
) -> Observation:
    actor, deny = _actor_or_deny(session, actor_id)
    if deny is not None:
        return deny
    assert actor is not None
    queues = visible_queues(actor.role)
    assert queues is not None
    stmt = select(Ticket).where(Ticket.queue.in_(queues))
    needle = query.strip()
    if needle:
        like = f"%{needle}%"
        stmt = stmt.where(
            or_(
                Ticket.id.like(like),
                Ticket.title.like(like),
                Ticket.description.like(like),
            )
        )
    tickets = list(session.scalars(stmt.order_by(Ticket.id)))
    return Observation(
        ok=True,
        code="ok",
        retryable=False,
        data={
            "tickets": [
                {
                    "id": t.id,
                    "title": t.title,
                    "status": t.status,
                    "queue": t.queue,
                    "priority": t.priority,
                    "requester_id": t.requester_id,
                    "asset_id": t.asset_id,
                }
                for t in tickets
            ]
        },
    )
