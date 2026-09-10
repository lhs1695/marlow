from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from marlow.models import Base, Employee
from marlow.seed import seed_if_empty

SQLITE_BUSY_TIMEOUT_MS = 5000


def _is_sqlite_memory(url: str) -> bool:
    return ":memory:" in url or url.endswith("sqlite://")


def make_engine(url: str = "sqlite:///:memory:") -> Engine:
    kwargs: dict = {}
    sqlite_memory = url.startswith("sqlite") and _is_sqlite_memory(url)
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if sqlite_memory:
            kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _enable_fk(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            if not sqlite_memory:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
            cursor.close()

    Base.metadata.create_all(engine)
    _ensure_run_cancel_column(engine)
    _ensure_approval_run_id_column(engine)
    return engine


def _ensure_run_cancel_column(engine: Engine) -> None:
    inspector = inspect(engine)
    if "runs" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("runs")}
    if "cancel_requested" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE runs ADD COLUMN cancel_requested BOOLEAN NOT NULL DEFAULT 0"))


def _ensure_approval_run_id_column(engine: Engine) -> None:
    inspector = inspect(engine)
    if "approvals" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("approvals")}
    if "run_id" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE approvals ADD COLUMN run_id VARCHAR(64)"))


def prepare_database(engine: Engine) -> None:
    with Session(engine) as session:
        seed_if_empty(session)
        session.commit()


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def make_session_factory(url: str = "sqlite:///:memory:") -> sessionmaker[Session]:
    engine = make_engine(url)
    prepare_database(engine)
    return sessionmaker(bind=engine)


def is_seeded(session: Session) -> bool:
    return session.scalar(select(Employee.id).limit(1)) is not None
