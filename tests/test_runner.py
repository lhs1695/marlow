from __future__ import annotations

import asyncio
import threading
import tempfile
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from marlow.db import make_engine, prepare_database
from marlow.engine import create_run
from marlow.models import Run
from marlow.runner import RunWorker
from marlow.seed import L1_ID


def test_engine_module_does_not_import_runner_or_web() -> None:
    source = (Path(__file__).resolve().parents[1] / "src" / "marlow" / "engine.py").read_text(encoding="utf-8")
    assert "marlow.runner" not in source
    assert "marlow.web" not in source


def test_worker_runs_one_job_at_a_time() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        engine = make_engine("sqlite:///" + (Path(tmp) / "worker.db").resolve().as_posix())
        prepare_database(engine)
        with Session(engine) as session:
            first = create_run(session, actor_id=L1_ID, user_text="请调查 INC-1001")
            second = create_run(session, actor_id=L1_ID, user_text="请调查 INC-1002")
            first_id = first.id
            second_id = second.id

        active = 0
        max_active = 0
        lock = threading.Lock()
        entered_first = threading.Event()
        release_first = threading.Event()

        def fake_start_run(session: Session, **kwargs: object) -> Run:
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            if kwargs.get("run_id") == first_id:
                entered_first.set()
                assert release_first.wait(timeout=5)
            with lock:
                active -= 1
            row = session.get(Run, kwargs["run_id"])
            assert row is not None
            return row

        from marlow import runner as runner_mod

        original = runner_mod.start_run
        runner_mod.start_run = fake_start_run  # type: ignore[method-assign]
        try:
            asyncio.run(_submit_two(engine, first_id, second_id, entered_first, release_first))
        finally:
            runner_mod.start_run = original  # type: ignore[method-assign]
            engine.dispose()
        assert max_active == 1
        assert entered_first.is_set()


async def _submit_two(
    engine: Engine,
    first_id: str,
    second_id: str,
    entered_first: threading.Event,
    release_first: threading.Event,
) -> None:
    worker = RunWorker(engine)
    await worker.start()
    await worker.submit(first_id, real=False)
    await worker.submit(second_id, real=False)
    assert await asyncio.to_thread(entered_first.wait, 5)
    release_first.set()
    await worker.stop()
