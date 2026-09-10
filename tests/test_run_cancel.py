from __future__ import annotations

import tempfile
import threading
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from marlow.codes import RUN_CANCELLED, RUN_COMPLETED
from marlow.db import make_engine, prepare_database
from marlow.engine import create_run, start_run
from marlow.models import Run
from marlow.observation import Observation
from marlow.seed import L1_ID
from marlow.tool_client import InProcessToolClient


class _PauseAfterFirstCall:
    def __init__(self, inner: InProcessToolClient, paused: threading.Event, hold: threading.Event) -> None:
        self._inner = inner
        self._paused = paused
        self._hold = hold
        self._calls = 0

    def call(self, name: str, *, actor_id: str, **arguments: object) -> Observation:
        obs = self._inner.call(name, actor_id=actor_id, **arguments)
        self._calls += 1
        if self._calls == 1:
            self._paused.set()
            assert self._hold.wait(timeout=5)
        return obs


def test_queued_cancel_finishes_cancelled_before_tools(session: Session) -> None:
    run = create_run(session, actor_id=L1_ID, user_text="请调查 INC-1001")
    run.cancel_requested = True
    session.commit()
    finished = start_run(
        session,
        actor_id=L1_ID,
        user_text="请调查 INC-1001",
        case_id="investigate",
        run_id=run.id,
    )
    assert finished.status == RUN_CANCELLED
    assert finished.outcome_code == RUN_CANCELLED
    assert "取消" in (finished.final_answer or "")


def test_cancel_takes_effect_between_steps() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        engine = make_engine("sqlite:///" + (Path(tmp) / "cancel.db").resolve().as_posix())
        prepare_database(engine)
        with Session(engine) as session:
            run = create_run(session, actor_id=L1_ID, user_text="请调查 INC-1001", case_id="investigate")
            run_id = run.id

        paused = threading.Event()
        hold = threading.Event()
        status_holder: dict[str, str] = {}
        error: list[BaseException] = []

        def worker() -> None:
            try:
                with Session(engine) as session:
                    finished = start_run(
                        session,
                        actor_id=L1_ID,
                        user_text="请调查 INC-1001",
                        case_id="investigate",
                        run_id=run_id,
                        tool_client=_PauseAfterFirstCall(
                            InProcessToolClient(session),
                            paused,
                            hold,
                        ),
                    )
                    status_holder["status"] = finished.status
            except BaseException as exc:  # noqa: BLE001 — surface in the joining thread
                error.append(exc)

        thread = threading.Thread(target=worker)
        thread.start()
        assert paused.wait(timeout=5)
        with Session(engine) as session:
            row = session.get(Run, run_id)
            assert row is not None
            row.cancel_requested = True
            session.commit()
        hold.set()
        thread.join(timeout=10)
        assert not thread.is_alive()
        assert error == []
        assert status_holder["status"] == RUN_CANCELLED
        with Session(engine) as session:
            final = session.get(Run, run_id)
            assert final is not None
            assert final.status == RUN_CANCELLED
            assert final.status != RUN_COMPLETED
            assert session.scalar(select(Run.status).where(Run.id == run_id)) == RUN_CANCELLED
        engine.dispose()
