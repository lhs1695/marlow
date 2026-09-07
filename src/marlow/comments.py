"""Low-risk write: ticket comments. Observation body is always untrusted."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from marlow.codes import QUEUE_CHANGE, ROLE_ADMIN, ROLE_L1, TICKET_NOT_FOUND, UNAUTHORIZED
from marlow.models import Employee, Ticket, TicketComment


@dataclass(frozen=True)
class CommentResult:
    ok: bool
    code: str
    untrusted: bool
    body: str | None = None
    comment_id: int | None = None


def add_ticket_comment(
    session: Session,
    *,
    actor_id: str,
    ticket_id: str,
    body: str,
) -> CommentResult:
    actor = session.get(Employee, actor_id)
    if actor is None or actor.role not in (ROLE_L1, ROLE_ADMIN):
        return CommentResult(ok=False, code=UNAUTHORIZED, untrusted=True)

    ticket = session.get(Ticket, ticket_id)
    if ticket is None:
        return CommentResult(ok=False, code=TICKET_NOT_FOUND, untrusted=True)

    if actor.role == ROLE_L1 and ticket.queue == QUEUE_CHANGE:
        return CommentResult(ok=False, code=UNAUTHORIZED, untrusted=True)

    row = TicketComment(ticket_id=ticket_id, author_id=actor_id, body=body)
    session.add(row)
    session.flush()
    return CommentResult(
        ok=True,
        code="ok",
        untrusted=True,
        body=row.body,
        comment_id=row.id,
    )
