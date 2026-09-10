import sqlite3
import threading
from pathlib import Path

from sqlalchemy import text

from marlow.db import SQLITE_BUSY_TIMEOUT_MS, make_engine, prepare_database


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


def _file_db(tmp_path: Path) -> Path:
    path = tmp_path / "wal.db"
    engine = make_engine("sqlite:///" + path.resolve().as_posix())
    prepare_database(engine)
    engine.dispose()
    return path


def test_wal_reader_sees_committed_snapshot_during_open_write(tmp_path: Path) -> None:
    path = _file_db(tmp_path)
    writer = sqlite3.connect(path, timeout=SQLITE_BUSY_TIMEOUT_MS / 1000)
    writer.execute("BEGIN")
    writer.execute("UPDATE tickets SET title='uncommitted-write' WHERE id='INC-1001'")
    reader = sqlite3.connect(path, timeout=SQLITE_BUSY_TIMEOUT_MS / 1000)
    try:
        title = reader.execute("SELECT title FROM tickets WHERE id='INC-1001'").fetchone()[0]
    finally:
        reader.close()
        writer.rollback()
        writer.close()
    assert title != "uncommitted-write"


def test_busy_timeout_waits_instead_of_raising_immediately(tmp_path: Path) -> None:
    path = _file_db(tmp_path)
    holder = sqlite3.connect(path, timeout=0)
    holder.execute("BEGIN IMMEDIATE")
    holder.execute("UPDATE tickets SET title=title WHERE id='INC-1001'")

    probe = sqlite3.connect(path, timeout=0)
    probe_error: BaseException | None = None
    try:
        probe.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as exc:
        probe_error = exc
    finally:
        probe.close()
    assert probe_error is not None
    assert "locked" in str(probe_error).lower()

    begin_issued = threading.Event()
    errors: list[BaseException] = []
    ok: list[bool] = []

    def waiter() -> None:
        conn = sqlite3.connect(path, timeout=SQLITE_BUSY_TIMEOUT_MS / 1000)
        conn.set_trace_callback(lambda sql: begin_issued.set() if "BEGIN" in sql.upper() else None)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE tickets SET title=title WHERE id='INC-1001'")
            conn.commit()
            ok.append(True)
        except BaseException as exc:
            errors.append(exc)
        finally:
            conn.close()

    thread = threading.Thread(target=waiter)
    thread.start()
    assert begin_issued.wait(timeout=5)
    holder.rollback()
    holder.close()
    thread.join(timeout=10)
    assert errors == []
    assert ok == [True]
