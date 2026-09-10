from pathlib import Path

from sqlalchemy import text

from marlow.db import SQLITE_BUSY_TIMEOUT_MS, make_engine


def test_file_sqlite_enables_wal_and_busy_timeout(tmp_path: Path) -> None:
    engine = make_engine("sqlite:///" + (tmp_path / "wal.db").resolve().as_posix())
    with engine.connect() as conn:
        journal = conn.execute(text("PRAGMA journal_mode")).scalar()
        timeout = conn.execute(text("PRAGMA busy_timeout")).scalar()
    assert str(journal).lower() == "wal"
    assert int(timeout) == SQLITE_BUSY_TIMEOUT_MS


def test_memory_sqlite_skips_wal() -> None:
    engine = make_engine("sqlite:///:memory:")
    with engine.connect() as conn:
        journal = conn.execute(text("PRAGMA journal_mode")).scalar()
    assert str(journal).lower() != "wal"
