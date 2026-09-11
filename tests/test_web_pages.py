from sqlalchemy import select
from sqlalchemy.orm import Session

from marlow.codes import PERM_EDITOR, PERM_VIEWER, STATUS_RESOLVED, SYSTEM_GRAFANA, UNAUTHORIZED
from marlow.engine import comment_count, ticket_status
from marlow.gateway import entitlement_permission
from marlow.models import TicketComment
from marlow.web.testids import (
    APPROVAL_APPROVE,
    APPROVAL_QUEUE,
    AUDIT_BLOCK,
    CHAT_CLARIFY,
    CHAT_DENY,
    ENTITLEMENT_PERMISSION,
    LOGIN_ADMIN,
    LOGIN_L1,
    PAGE_CLAIM,
    REJECT_NOTICE,
    ROLE,
    TICKET_COMMENTS,
    TICKET_ID,
    TICKET_LIST,
    TICKET_STATUS,
)
from tests.web_helpers import app_client, login_form, post_chat_wait, wait_for_run


def _form_login(client, account: str) -> None:
    login_form(client, account)
    expected_role = "admin" if account == "admin" else "l1"
    page = client.get("/tickets")
    assert f'data-testid="{ROLE}">{expected_role}</span>' in page.text


def test_login_page_has_account_testids() -> None:
    with app_client() as (client, _engine):
        page = client.get("/")
        assert page.status_code == 200
        assert f'data-testid="{LOGIN_L1}"' in page.text
        assert f'data-testid="{LOGIN_ADMIN}"' in page.text
        assert "<summary>示例</summary>" in page.text
        assert "关单以工单库与审计终态为准" in page.text
        assert "写权限" in page.text
        assert "写 entitlements" not in page.text
        assert "HTTP 200" not in page.text
        assert "模型说成功" not in page.text


def test_l1_list_has_no_unapproved_grant_success() -> None:
    with app_client() as (client, _engine):
        _form_login(client, "l1")
        page = client.get("/tickets")
        assert page.status_code == 200
        assert f'data-testid="{TICKET_LIST}"' in page.text
        assert f'data-testid="{ROLE}">l1</span>' in page.text
        assert "CHG-2001" not in page.text
        assert "INC-1001" in page.text
        assert "权限已变更" not in page.text
        assert "已授权成功" not in page.text
        assert f'data-testid="{APPROVAL_APPROVE}"' not in page.text
        assert "pill-demo" not in page.text
        assert "HTTP 200" not in page.text
        assert "优先级" in page.text


def test_l1_detail_testids_and_query_role_still_l1() -> None:
    with app_client() as (client, engine):
        _form_login(client, "l1")
        page = client.get("/tickets/INC-1001", params={"role": "admin"})
        assert page.status_code == 200
        assert f'data-testid="{TICKET_ID}">INC-1001</span>' in page.text
        assert f'data-testid="{TICKET_STATUS}"' in page.text
        assert f'data-testid="{TICKET_COMMENTS}"' in page.text
        assert f'data-testid="{AUDIT_BLOCK}"' in page.text
        assert f'data-testid="{ROLE}">l1</span>' in page.text
        assert f'data-testid="{PAGE_CLAIM}"' in page.text
        assert "admin" in page.text
        res = client.post(
            "/api/entitlements",
            json={
                "ticket_id": "CHG-2004",
                "target_employee_id": "emp-007",
                "system": SYSTEM_GRAFANA,
                "new_permission": PERM_EDITOR,
                "idempotency_key": "html-fake-admin",
                "role": "admin",
            },
            params={"role": "admin"},
        )
        assert res.status_code == 403
        with Session(engine) as db:
            assert entitlement_permission(db, "emp-007", SYSTEM_GRAFANA) == PERM_VIEWER


def test_chat_without_ticket_clarifies_and_does_not_comment() -> None:
    with app_client() as (client, engine):
        _form_login(client, "l1")
        with Session(engine) as db:
            before = comment_count(db)
        page, _run_id = post_chat_wait(
            client,
            {"text": "Grafana 登录有问题，帮我看看", "next": "/tickets"},
        )
        assert f'data-testid="{CHAT_CLARIFY}"' in page.text
        assert "工单号" in page.text
        with Session(engine) as db:
            assert comment_count(db) == before


def test_chat_client_case_id_cannot_force_close() -> None:
    with app_client() as (client, engine):
        _form_login(client, "l1")
        _page, _run_id = post_chat_wait(
            client,
            {"text": "请关 INC-1002", "case_id": "close_success", "next": "/tickets"},
        )
        with Session(engine) as db:
            assert ticket_status(db, "INC-1002") == "Investigating"


def test_chat_inc_1001_closes_with_citation() -> None:
    with app_client() as (client, engine):
        _form_login(client, "l1")
        _page, _run_id = post_chat_wait(
            client,
            {"text": "请调查 INC-1001 并关单", "next": "/tickets"},
        )
        with Session(engine) as db:
            assert ticket_status(db, "INC-1001") == STATUS_RESOLVED
            closing = [
                row.body
                for row in db.scalars(select(TicketComment).where(TicketComment.ticket_id == "INC-1001"))
                if "ticket_id=INC-1001" in row.body and "grafana-login@10.4" in row.body
            ]
            assert closing


def test_l1_chat_on_change_ticket_shows_deny_entitlements_unchanged() -> None:
    with app_client() as (client, engine):
        _form_login(client, "l1")
        page, _run_id = post_chat_wait(
            client,
            {"text": "请在 CHG-2004 上改权限", "next": "/tickets"},
        )
        assert f'data-testid="{CHAT_DENY}"' in page.text
        with Session(engine) as db:
            assert entitlement_permission(db, "emp-007", SYSTEM_GRAFANA) == PERM_VIEWER


def test_admin_reject_shows_notice_permission_unchanged() -> None:
    with app_client() as (client, engine):
        _form_login(client, "admin")
        queue = client.get("/approvals")
        assert queue.status_code == 200
        assert f'data-testid="{APPROVAL_QUEUE}"' in queue.text
        assert f'data-testid="{APPROVAL_APPROVE}"' in queue.text
        rejected = client.post(
            "/approvals",
            data={
                "ticket_id": "CHG-2003",
                "target_employee_id": "emp-006",
                "decision": "reject",
            },
            follow_redirects=True,
        )
        assert rejected.status_code == 200
        assert f'data-testid="{REJECT_NOTICE}"' in rejected.text
        assert f'data-testid="{ENTITLEMENT_PERMISSION}">Viewer</span>' in rejected.text
        with Session(engine) as db:
            assert ticket_status(db, "CHG-2003") == "Rejected"
            assert entitlement_permission(db, "emp-006", SYSTEM_GRAFANA) == PERM_VIEWER


def test_l1_cannot_open_approvals_or_change_detail() -> None:
    with app_client() as (client, _engine):
        _form_login(client, "l1")
        assert client.get("/approvals").status_code == 403
        denied = client.get("/tickets/CHG-2001")
        assert denied.status_code == 403
        assert denied.json()["detail"] == UNAUTHORIZED
        post = client.post(
            "/approvals",
            data={
                "ticket_id": "CHG-2004",
                "target_employee_id": "emp-007",
                "decision": "approve",
            },
        )
        assert post.status_code == 403


def test_admin_new_change_ticket_has_no_decision_buttons() -> None:
    with app_client() as (client, _engine):
        _form_login(client, "admin")
        seeded_new = client.get("/tickets/CHG-2001")
        assert seeded_new.status_code == 200
        assert f'data-testid="{APPROVAL_APPROVE}"' not in seeded_new.text
        waiting = client.get("/tickets/CHG-2004")
        assert waiting.status_code == 200
        assert f'data-testid="{APPROVAL_APPROVE}"' in waiting.text


def test_chat_keeps_run_id_after_another_get() -> None:
    with app_client() as (client, _engine):
        _form_login(client, "l1")
        page, run_id = post_chat_wait(
            client,
            {"text": "Grafana 登录有问题，帮我看看", "next": "/tickets"},
        )
        wait_for_run(client, run_id)
        again = client.get("/tickets")
        assert f'data-testid="{CHAT_CLARIFY}"' in again.text
        assert "run_id=" in again.text
        assert "/api/runs/" in again.text
        assert page.status_code == 200


def test_static_css_is_served() -> None:
    with app_client() as (client, _engine):
        css = client.get("/static/app.css")
        assert css.status_code == 200
        assert "--accent" in css.text
        assert ":focus-visible" in css.text
        icon = client.get("/static/favicon.svg")
        assert icon.status_code == 200
        assert "<svg" in icon.text
        js = client.get("/static/app.js")
        assert js.status_code == 200
        assert "EventSource" in js.text


def test_l1_can_add_comment_on_incident() -> None:
    with app_client() as (client, engine):
        _form_login(client, "l1")
        res = client.post(
            "/tickets/INC-1001/comments",
            data={"body": "现场核对登录页。"},
            follow_redirects=True,
        )
        assert res.status_code == 200
        assert "现场核对登录页。" in res.text
        with Session(engine) as db:
            assert entitlement_permission(db, "emp-003", SYSTEM_GRAFANA) == PERM_VIEWER
