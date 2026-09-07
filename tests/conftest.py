from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from marlow.db import make_engine, prepare_database


@pytest.fixture
def session() -> Iterator[Session]:
    engine = make_engine("sqlite:///:memory:")
    prepare_database(engine)
    with Session(engine) as db:
        yield db
