from __future__ import annotations

from pathlib import Path

from marlow.codes import RUN_COMPLETED
from marlow.models import Run
from sqlalchemy.orm import Session

from tests.web_helpers import app_client, login_json, parse_sse, wait_for_run


def test_waiting_approval_sse_branch_is_kept() -> None:
    source = (Path(__file__).resolve().parents[1] / "src" / "marlow" / "web" / "app.py").read_text(
        encoding="utf-8"
    )
    assert "RUN_WAITING_APPROVAL" in source
    assert 'kind == "waiting_approval"' in source


def test_sse_last_event_id_replays_only_later_events() -> None:
    with app_client() as (client, _engine):
        login_json(client)
        created = client.post("/api/runs", json={"text": "请调查 INC-1001"})
        assert created.status_code == 202, created.text
        run_id = created.json()["run_id"]
        wait_for_run(client, run_id)
        full = client.get(f"/api/runs/{run_id}/events")
        assert full.status_code == 200
        events = [item for item in parse_sse(full.text) if item["event"] != "done"]
        ids = [item["id"] for item in events if item["id"] is not None]
        assert ids == sorted(ids)
        assert len(ids) >= 3
        pivot = ids[2]
        resumed = client.get(
            f"/api/runs/{run_id}/events",
            headers={"Last-Event-ID": str(pivot)},
        )
        assert resumed.status_code == 200
        replayed = parse_sse(resumed.text)
        replayed_ids = [item["id"] for item in replayed if item["id"] is not None]
        assert replayed_ids == [event_id for event_id in ids if event_id > pivot]
        assert replayed[-1]["event"] == "done"
        assert all(event_id > pivot for event_id in replayed_ids)


def test_sse_disconnect_does_not_cancel_run() -> None:
    with app_client() as (client, engine):
        login_json(client)
        created = client.post("/api/runs", json={"text": "请调查 INC-1001"})
        assert created.status_code == 202, created.text
        run_id = created.json()["run_id"]
        last_id = None
        with client.stream("GET", f"/api/runs/{run_id}/events") as response:
            assert response.status_code == 200
            for line in response.iter_lines():
                if line.startswith("id:"):
                    last_id = int(line.split(":", 1)[1].strip())
                    break
        assert last_id is not None
        resumed = client.get(
            f"/api/runs/{run_id}/events",
            headers={"Last-Event-ID": str(last_id)},
        )
        assert resumed.status_code == 200
        assert "event: done" in resumed.text
        body = client.get(f"/api/runs/{run_id}").json()
        assert body["status"] == RUN_COMPLETED
        assert body["cancel_requested"] is False
        with Session(engine) as db:
            row = db.get(Run, run_id)
            assert row is not None
            assert row.cancel_requested is False


def test_cancel_endpoint_sets_column() -> None:
    with app_client() as (client, engine):
        login_json(client)
        created = client.post("/api/runs", json={"text": "请调查 INC-1001"})
        run_id = created.json()["run_id"]
        cancelled = client.post(f"/api/runs/{run_id}/cancel")
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["cancel_requested"] is True
        with Session(engine) as db:
            row = db.get(Run, run_id)
            assert row is not None
            assert row.cancel_requested is True
        wait_for_run(client, run_id)


def test_cancel_requires_auth() -> None:
    with app_client() as (client, _engine):
        login_json(client)
        created = client.post("/api/runs", json={"text": "请调查 INC-1001"})
        run_id = created.json()["run_id"]
        wait_for_run(client, run_id)
        client.post("/logout")
        denied = client.post(f"/api/runs/{run_id}/cancel")
        assert denied.status_code == 401


def test_run_get_requires_auth() -> None:
    with app_client() as (client, _engine):
        login_json(client)
        created = client.post("/api/runs", json={"text": "Grafana 登录有问题，帮我看看"})
        run_id = created.json()["run_id"]
        wait_for_run(client, run_id)
        client.post("/logout")
        denied = client.get(f"/api/runs/{run_id}")
        assert denied.status_code == 401
