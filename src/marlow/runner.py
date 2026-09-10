"""One Run at a time. Events fan out in-process; multi-replica would swap publish() for Redis."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from marlow.codes import NON_RETRYABLE, RUN_FAILED, TERMINAL_RUN_STATUSES
from marlow.engine import http_fake_faults, latest_checkpoint, resume_run, start_run
from marlow.llm import want_real_llm
from marlow.models import AgentSession, Run, RunEvent

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunJob:
    run_id: str
    real: bool = False


class RunWorker:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._jobs: asyncio.Queue[RunJob] = asyncio.Queue()
        self._subs: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        self._sub_lock = threading.Lock()
        self._task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stopping = False

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stopping = False
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.create_task(self._worker_loop(), name="marlow-run-worker")

    async def stop(self) -> None:
        self._stopping = True
        await self._jobs.join()
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def submit(self, run_id: str, *, real: bool | None = None) -> None:
        if self._task is None or self._task.done():
            await self.start()
        await self._jobs.put(RunJob(run_id=run_id, real=want_real_llm() if real is None else real))

    def subscribe(self, run_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        with self._sub_lock:
            self._subs[run_id].add(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        with self._sub_lock:
            bucket = self._subs.get(run_id)
            if bucket is None:
                return
            bucket.discard(queue)
            if not bucket:
                self._subs.pop(run_id, None)

    def publish(self, event: dict[str, Any]) -> None:
        run_id = str(event.get("run_id") or "")
        loop = self._loop
        if not run_id or loop is None:
            return
        with self._sub_lock:
            queues = list(self._subs.get(run_id, ()))
        for queue in queues:
            loop.call_soon_threadsafe(self._put_nowait, queue, event)

    def _put_nowait(self, queue: asyncio.Queue[dict[str, Any]], event: dict[str, Any]) -> None:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            log.warning("dropping run event; subscriber queue is full")

    async def _worker_loop(self) -> None:
        while True:
            job = await self._jobs.get()
            try:
                await run_in_threadpool(self._execute, job)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("run worker failed run_id=%s", job.run_id)
            finally:
                self._jobs.task_done()

    def _execute(self, job: RunJob) -> None:
        with Session(self.engine) as session:
            run = session.get(Run, job.run_id)
            if run is None:
                return
            if run.status in TERMINAL_RUN_STATUSES:
                return
            try:
                if latest_checkpoint(session, run.id) is not None:
                    resume_run(
                        session,
                        run_id=run.id,
                        faults=http_fake_faults(run.user_text),
                        real=job.real,
                        on_event=self.publish,
                    )
                else:
                    start_run(
                        session,
                        actor_id=run.actor_id,
                        user_text=run.user_text,
                        case_id=run.case_id,
                        session_id=run.session_id,
                        run_id=run.id,
                        faults=http_fake_faults(run.user_text),
                        real=job.real,
                        on_event=self.publish,
                    )
            except Exception:
                session.rollback()
                failed = session.get(Run, job.run_id)
                if failed is not None and failed.status not in TERMINAL_RUN_STATUSES:
                    _mark_failed(session, failed)
                    self.publish(
                        {
                            "id": None,
                            "run_id": failed.id,
                            "kind": "state",
                            "payload": json.dumps({"status": RUN_FAILED}),
                            "request_id": failed.request_id,
                            "trace_id": failed.trace_id,
                            "status": RUN_FAILED,
                            "outcome_code": NON_RETRYABLE,
                            "final_answer": failed.final_answer,
                        }
                    )
                raise


def _mark_failed(session: Session, run: Run) -> None:
    run.status = RUN_FAILED
    run.outcome_code = NON_RETRYABLE
    run.final_answer = "Run 执行失败。"
    session.add(
        RunEvent(
            run_id=run.id,
            kind="state",
            payload=json.dumps({"status": RUN_FAILED}),
        )
    )
    agent_session = session.get(AgentSession, run.session_id)
    if agent_session is not None:
        agent_session.summary = f"{run.case_id or 'run'} {NON_RETRYABLE} ticket={run.ticket_id or '-'}"
    session.commit()
