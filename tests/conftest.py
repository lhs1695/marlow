from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from marlow.db import make_engine, prepare_database
from marlow.stdio import ensure_utf8_stdio

ensure_utf8_stdio()


def pytest_configure(config: pytest.Config) -> None:
    ensure_utf8_stdio()


def pytest_sessionstart(session: pytest.Session) -> None:
    ensure_utf8_stdio()


@pytest.fixture(autouse=True)
def _keep_pytest_on_fake_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MARLOW_LLM", raising=False)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = make_engine("sqlite:///:memory:")
    prepare_database(engine)
    with Session(engine) as db:
        yield db
