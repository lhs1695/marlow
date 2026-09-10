from __future__ import annotations

import json
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from marlow.codes import TERMINAL_RUN_STATUSES
from marlow.db import make_engine, prepare_database
from marlow.web.app import create_app


@contextmanager
def app_client(**kwargs) -> Iterator[tuple[TestClient, Engine]]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "marlow.db"
        engine = make_engine("sqlite:///" + path.resolve().as_posix())
        prepare_database(engine)
        try:
            with TestClient(create_app(engine, **kwargs)) as client:
                yield client, engine
        finally:
            engine.dispose()


def login_json(client: TestClient, account: str = "l1", password: str = "l1-demo") -> None:
    res = client.post("/login", json={"account": account, "password": password})
    assert res.status_code == 200, res.text
    assert res.json()["role"] in {"l1", "admin"}


def login_form(client: TestClient, account: str) -> None:
    password = "admin-demo" if account == "admin" else "l1-demo"
    res = client.post("/login", data={"account": account, "password": password}, follow_redirects=True)
    assert res.status_code == 200, res.text


def wait_for_run(client: TestClient, run_id: str) -> dict:
    stream = client.get(f"/api/runs/{run_id}/events")
    assert stream.status_code == 200, stream.text
    assert "event: done" in stream.text
    res = client.get(f"/api/runs/{run_id}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] in TERMINAL_RUN_STATUSES, body
    return body


def run_id_from_location(location: str) -> str:
    values = parse_qs(urlparse(location).query).get("run_id") or []
    assert values, location
    return values[0]


def post_chat_wait(client: TestClient, data: dict[str, str]) -> tuple[object, str]:
    res = client.post("/chat", data=data, follow_redirects=False)
    assert res.status_code == 303, res.text
    location = res.headers["location"]
    run_id = run_id_from_location(location)
    wait_for_run(client, run_id)
    page = client.get(location)
    assert page.status_code == 200, page.text
    return page, run_id


def parse_sse(text: str) -> list[dict]:
    events: list[dict] = []
    event_id = None
    event_name = None
    data_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("id:"):
            event_id = int(line[3:].strip())
        elif line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
        elif line == "":
            if event_name is not None:
                payload = json.loads("\n".join(data_lines) or "{}")
                events.append({"id": event_id, "event": event_name, "data": payload})
            event_id = None
            event_name = None
            data_lines = []
    return events
