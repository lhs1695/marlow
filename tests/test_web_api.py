from sqlalchemy.orm import Session

from marlow.codes import PERM_EDITOR, PERM_VIEWER, STATUS_INVESTIGATING, STATUS_RESOLVED, SYSTEM_GRAFANA, UNAUTHORIZED
from marlow.engine import ticket_status
from marlow.gateway import entitlement_permission
from marlow.web.limits import MemoryRateLimiter
from tests.web_helpers import app_client, login_json, wait_for_run


def test_unauthenticated_entitlement_post_does_not_write() -> None:
    with app_client() as (client, engine):
        with Session(engine) as db:
            before = entitlement_permission(db, "emp-007", SYSTEM_GRAFANA)
            assert before == PERM_VIEWER
            res = client.post(
                "/api/entitlements",
                json={
                    "ticket_id": "CHG-2004",
                    "target_employee_id": "emp-007",
                    "system": SYSTEM_GRAFANA,
                    "new_permission": PERM_EDITOR,
                    "decision": "approve",
                    "idempotency_key": "web-unauth",
                },
            )
            assert res.status_code == 401
            db.expire_all()
            assert entitlement_permission(db, "emp-007", SYSTEM_GRAFANA) == PERM_VIEWER


def test_l1_change_ticket_url_is_403_even_with_forged_admin() -> None:
    with app_client() as (client, _engine):
        login_json(client, "l1", "l1-demo")
        res = client.get(
            "/tickets/CHG-2001",
            params={"role": "admin"},
            headers={"X-Role": "admin", "X-Actor-Role": "admin"},
        )
        assert res.status_code == 403
        assert res.json()["detail"] == UNAUTHORIZED
        me = client.get("/me", params={"role": "admin"})
        assert me.status_code == 200
        assert me.json()["role"] == "l1"


def test_create_investigate_run_sse_has_step_events() -> None:
    with app_client() as (client, _engine):
        login_json(client)
        created = client.post(
            "/api/runs",
            json={"text": "请调查 INC-1001", "case_id": "investigate", "role": "admin"},
            params={"role": "admin"},
        )
        assert created.status_code == 202, created.text
        body = created.json()
        assert body["request_id"]
        assert body["trace_id"]
        assert body["request_id"] != body["trace_id"]
        assert body["run_id"] == body["request_id"]
        assert "status" not in body
        assert "outcome_code" not in body
        assert "final_answer" not in body
        stream = client.get(f"/api/runs/{body['run_id']}/events")
        assert stream.status_code == 200
        assert "text/event-stream" in stream.headers["content-type"]
        text = stream.text
        assert "event: step" in text
        assert "event: done" in text
        assert body["request_id"] in text
        assert body["trace_id"] in text
        assert "event: tool" in text or "skill" in text
        final = client.get(f"/api/runs/{body['run_id']}")
        assert final.status_code == 200
        assert final.json()["status"]


def test_input_too_long_is_rejected() -> None:
    with app_client() as (client, _engine):
        login_json(client)
        res = client.post("/api/runs", json={"text": "x" * 4001, "case_id": "investigate"})
        assert res.status_code == 400
        assert res.json()["detail"] == "input_too_long"


def test_rate_limit_on_runs() -> None:
    with app_client(limiter=MemoryRateLimiter(max_hits=2, window_s=60)) as (client, _engine):
        login_json(client)
        ok1 = client.post("/api/runs", json={"text": "请调查 INC-1001", "case_id": "investigate"})
        ok2 = client.post("/api/runs", json={"text": "请调查 INC-1001", "case_id": "investigate"})
        blocked = client.post("/api/runs", json={"text": "请调查 INC-1001", "case_id": "investigate"})
        assert ok1.status_code == 202
        assert ok2.status_code == 202
        assert blocked.status_code == 429


def test_web_ignores_client_fake_case_id_and_does_not_close() -> None:
    with app_client() as (client, engine):
        login_json(client)
        res = client.post(
            "/api/runs",
            json={"text": "请关 INC-1002", "case_id": "close_success", "role": "admin"},
            params={"case_id": "close_success", "role": "admin"},
        )
        assert res.status_code == 202, res.text
        wait_for_run(client, res.json()["run_id"])
        with Session(engine) as db:
            assert ticket_status(db, "INC-1002") == STATUS_INVESTIGATING
            assert ticket_status(db, "INC-1002") != STATUS_RESOLVED


def test_l1_entitlement_api_still_uses_gateway() -> None:
    with app_client() as (client, engine):
        login_json(client, "l1", "l1-demo")
        with Session(engine) as db:
            before = entitlement_permission(db, "emp-007", SYSTEM_GRAFANA)
        res = client.post(
            "/api/entitlements",
            json={
                "ticket_id": "CHG-2004",
                "target_employee_id": "emp-007",
                "system": SYSTEM_GRAFANA,
                "new_permission": PERM_EDITOR,
                "decision": "approve",
                "idempotency_key": "web-l1",
                "role": "admin",
            },
            params={"role": "admin"},
        )
        assert res.status_code == 403
        with Session(engine) as db:
            assert entitlement_permission(db, "emp-007", SYSTEM_GRAFANA) == before == PERM_VIEWER
