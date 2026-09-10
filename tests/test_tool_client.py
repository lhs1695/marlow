import inspect
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from marlow.codes import STATUS_RESOLVED
from marlow.db import make_engine, prepare_database
from marlow.engine import start_run
from marlow.fake import provider_for_case
from marlow.models import AuditEvent, Ticket
from marlow.seed import L1_ID
from marlow.tool_client import InProcessToolClient, StdioMCPClient, ToolClient

_CASES = (
    ("investigate", "请调查 INC-1001"),
    ("close_success", "请调查 INC-1001 并关单"),
)


def test_tool_client_call_has_no_session_parameter() -> None:
    for cls in (InProcessToolClient, StdioMCPClient):
        assert "session" not in inspect.signature(cls.call).parameters
    assert "session" not in inspect.signature(ToolClient.call).parameters


def _column_dicts(session: Session, model: type, *, skip: frozenset[str] = frozenset()) -> list[dict[str, object]]:
    rows = list(session.scalars(select(model).order_by(model.id)))
    keys = [column.key for column in model.__table__.columns if column.key not in skip]
    return [{key: getattr(row, key) for key in keys} for row in rows]


def _run_case(db_path: Path, case_id: str, user_text: str, *, stdio: bool) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    url = "sqlite:///" + db_path.resolve().as_posix()
    engine = make_engine(url)
    prepare_database(engine)
    client: InProcessToolClient | StdioMCPClient | None = None
    try:
        with Session(engine) as session:
            if stdio:
                client = StdioMCPClient(url)
            else:
                client = InProcessToolClient(session)
            start_run(
                session,
                actor_id=L1_ID,
                user_text=user_text,
                case_id=case_id,
                provider=provider_for_case(case_id),
                tool_client=client,
            )
            tickets = _column_dicts(session, Ticket)
            audits = _column_dicts(session, AuditEvent, skip=frozenset({"created_at"}))
    finally:
        if isinstance(client, StdioMCPClient):
            client.close()
    return tickets, audits


@pytest.mark.parametrize(("case_id", "user_text"), _CASES)
def test_inprocess_and_stdio_match_tickets_and_audit(
    tmp_path: Path,
    case_id: str,
    user_text: str,
) -> None:
    in_tickets, in_audits = _run_case(tmp_path / "inprocess.db", case_id, user_text, stdio=False)
    stdio_tickets, stdio_audits = _run_case(tmp_path / "stdio.db", case_id, user_text, stdio=True)
    assert stdio_tickets == in_tickets
    assert stdio_audits == in_audits
    if case_id == "close_success":
        assert any(row["id"] == "INC-1001" and row["status"] == STATUS_RESOLVED for row in stdio_tickets)
