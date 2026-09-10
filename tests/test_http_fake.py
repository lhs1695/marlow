from sqlalchemy import select
from sqlalchemy.orm import Session

from marlow.codes import (
    PERM_VIEWER,
    RETRYABLE_TIMEOUT,
    STATUS_INVESTIGATING,
    STATUS_RESOLVED,
    SYSTEM_GRAFANA,
)
from marlow.engine import http_fake_case_id, ticket_status
from marlow.gateway import entitlement_permission
from marlow.models import TicketComment
from tests.web_helpers import app_client, login_json, wait_for_run


def test_http_fake_case_id_maps_seeds_only() -> None:
    assert http_fake_case_id("Grafana 登录有问题，帮我看看") is None
    assert http_fake_case_id("请调查 INC-1001 并关单") == "close_success"
    assert http_fake_case_id("读取 INC-1005 的资产配置") == "timeout"
    assert http_fake_case_id("请在 CHG-2004 上改权限") == "investigate"
    assert http_fake_case_id("请关 INC-1002") == "investigate"
    assert http_fake_case_id("请关 INC-1002") != "close_success"


def test_http_inc_1001_closes_without_client_case_id() -> None:
    with app_client() as (client, engine):
        login_json(client)
        res = client.post("/api/runs", json={"text": "请调查 INC-1001 并关单"})
        assert res.status_code == 202, res.text
        body = wait_for_run(client, res.json()["run_id"])
        assert body["outcome_code"] == "ok"
        with Session(engine) as db:
            assert ticket_status(db, "INC-1001") == STATUS_RESOLVED
            closing = [
                row.body
                for row in db.scalars(select(TicketComment).where(TicketComment.ticket_id == "INC-1001"))
                if "ticket_id=INC-1001" in row.body and "grafana-login@10.4" in row.body
            ]
            assert closing


def test_http_body_and_query_case_id_cannot_select_close_script() -> None:
    with app_client() as (client, engine):
        login_json(client)
        res = client.post(
            "/api/runs",
            json={"text": "请关 INC-1002", "case_id": "close_success"},
            params={"case_id": "close_success"},
        )
        assert res.status_code == 202, res.text
        wait_for_run(client, res.json()["run_id"])
        with Session(engine) as db:
            assert ticket_status(db, "INC-1002") == STATUS_INVESTIGATING
            assert ticket_status(db, "INC-1002") != STATUS_RESOLVED


def test_http_inc_1005_timeout_does_not_fake_success() -> None:
    with app_client() as (client, engine):
        login_json(client)
        res = client.post(
            "/api/runs",
            json={"text": "读取 INC-1005 的资产配置", "case_id": "close_success"},
        )
        assert res.status_code == 202, res.text
        body = wait_for_run(client, res.json()["run_id"])
        assert body["outcome_code"] == RETRYABLE_TIMEOUT
        answer = body["final_answer"] or ""
        assert "降级" in answer
        assert "已授权成功" not in answer
        assert "资产正常" not in answer
        with Session(engine) as db:
            assert ticket_status(db, "INC-1005") == STATUS_INVESTIGATING
            assert entitlement_permission(db, "emp-007", SYSTEM_GRAFANA) == PERM_VIEWER


def test_http_chg_2004_does_not_close() -> None:
    with app_client() as (client, engine):
        login_json(client)
        res = client.post(
            "/api/runs",
            json={"text": "请在 CHG-2004 上改权限", "case_id": "close_success"},
        )
        assert res.status_code == 202, res.text
        wait_for_run(client, res.json()["run_id"])
        with Session(engine) as db:
            assert ticket_status(db, "CHG-2004") != STATUS_RESOLVED
            assert entitlement_permission(db, "emp-007", SYSTEM_GRAFANA) == PERM_VIEWER
