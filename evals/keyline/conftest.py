"""Put `evals/` on sys.path so `import keyline` works under pytest."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from marlow.db import make_engine, prepare_database

_evals_dir = Path(__file__).resolve().parent.parent
_evals_str = str(_evals_dir)
if _evals_str not in sys.path:
    sys.path.insert(0, _evals_str)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = make_engine("sqlite:///:memory:")
    prepare_database(engine)
    with Session(engine) as db:
        yield db
