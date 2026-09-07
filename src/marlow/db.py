from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from marlow.models import Base, Employee
from marlow.seed import seed_if_empty


def make_engine(url: str = "sqlite:///:memory:") -> Engine:
    kwargs: dict = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url or url.endswith("sqlite://"):
            kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _enable_fk(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    Base.metadata.create_all(engine)
    return engine


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
