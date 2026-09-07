from sqlalchemy import func, select

from marlow.codes import PERM_VIEWER, QUEUE_CHANGE, QUEUE_L1, SYSTEM_GRAFANA
from marlow.comments import add_ticket_comment
from marlow.gateway import entitlement_permission
from marlow.models import Asset, Employee, Ticket, TicketComment
from marlow.seed import INJECTION_COMMENT, L1_ID


def test_seed_counts_and_eval_vehicles(session) -> None:
    assert session.scalar(select(func.count()).select_from(Employee)) == 8
    assert session.scalar(select(func.count()).select_from(Asset)) == 3
    assert session.scalar(select(func.count()).select_from(Ticket)) == 15
    queues = set(session.scalars(select(Ticket.queue)).all())
    assert queues == {QUEUE_L1, QUEUE_CHANGE}
    waiting = list(
        session.scalars(select(Ticket).where(Ticket.status == "Waiting for approval"))
    )
    assert waiting
    injected = session.scalar(
        select(TicketComment).where(TicketComment.body == INJECTION_COMMENT)
    )
    assert injected is not None
    assert injected.ticket_id == "INC-1010"
    assert session.get(Ticket, "INC-9999") is None


def test_l1_comment_allowed_and_marked_untrusted(session) -> None:
    before = entitlement_permission(session, "emp-003", SYSTEM_GRAFANA)
    result = add_ticket_comment(
        session,
        actor_id=L1_ID,
        ticket_id="INC-1001",
        body="Investigating login path.",
    )
    session.flush()
    assert result.ok is True
    assert result.untrusted is True
    assert entitlement_permission(session, "emp-003", SYSTEM_GRAFANA) == before == PERM_VIEWER
