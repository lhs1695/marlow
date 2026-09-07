from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from marlow.codes import PERM_EDITOR, PERM_VIEWER, SYSTEM_GRAFANA, UNAUTHORIZED
from marlow.db import make_engine, prepare_database
from marlow.engine import comment_count, ticket_status
from marlow.gateway import entitlement_permission
from marlow.web.app import create_app
from marlow.web.testids import (
    APPROVAL_APPROVE,
    APPROVAL_QUEUE,
    AUDIT_BLOCK,
    CHAT_CLARIFY,
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


def _app_client() -> tuple[TestClient, object]:
    engine = make_engine("sqlite:///:memory:")
    prepare_database(engine)
    return TestClient(create_app(engine)), engine


def _form_login(client: TestClient, account: str) -> None:
    password = "admin-demo" if account == "admin" else "l1-demo"
    res = client.post("/login", data={"account": account, "password": password}, follow_redirects=True)
    assert res.status_code == 200, res.text
    expected_role = "admin" if account == "admin" else "l1"
    assert f'data-testid="{ROLE}">{expected_role}</span>' in res.text


def test_login_page_has_account_testids() -> None:
    client, _engine = _app_client()
    page = client.get("/")
    assert page.status_code == 200
    assert f'data-testid="{LOGIN_L1}"' in page.text
    assert f'data-testid="{LOGIN_ADMIN}"' in page.text


def test_l1_list_has_no_unapproved_grant_success() -> None:
    client, _engine = _app_client()
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


def test_l1_detail_testids_and_query_role_still_l1() -> None:
    client, engine = _app_client()
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
    client, engine = _app_client()
    _form_login(client, "l1")
    with Session(engine) as db:
        before = comment_count(db)
    page = client.post(
        "/chat",
        data={"text": "Grafana 登录有问题，帮我看看", "next": "/tickets"},
        follow_redirects=True,
    )
    assert page.status_code == 200
    assert f'data-testid="{CHAT_CLARIFY}"' in page.text
    assert "工单号" in page.text
    with Session(engine) as db:
        assert comment_count(db) == before


def test_admin_reject_shows_notice_permission_unchanged() -> None:
    client, engine = _app_client()
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
    client, _engine = _app_client()
    _form_login(client, "l1")
    assert client.get("/approvals").status_code == 403
    denied = client.get("/tickets/CHG-2001")
    assert denied.status_code == 403
    assert denied.json()["detail"] == UNAUTHORIZED


def test_l1_can_add_comment_on_incident() -> None:
    client, engine = _app_client()
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
