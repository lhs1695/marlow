from marlow.web.testids import ROLE

from keyline.playwright_solver import (
    assert_approval_queue,
    assert_role,
    assert_ticket_id,
    assert_ticket_list,
    by_testid,
    login,
    open_path,
)


def test_l1_login_opens_ticket_list(live_app, page) -> None:
    base = live_app["base_url"]
    login(page, base, "l1")
    assert page.url.rstrip("/").endswith("/tickets")
    assert_ticket_list(page)


def test_admin_sees_approval_queue(live_app, page) -> None:
    base = live_app["base_url"]
    login(page, base, "admin")
    open_path(page, base, "/approvals")
    assert "/approvals" in page.url
    assert_role(page, "admin")
    assert_approval_queue(page)


def test_l1_query_role_admin_stays_l1(live_app, page) -> None:
    base = live_app["base_url"]
    login(page, base, "l1")
    open_path(page, base, "/tickets?role=admin")
    assert "role=admin" in page.url
    assert_role(page, "l1")
    assert_ticket_list(page)
    open_path(page, base, "/tickets/INC-1001?role=admin")
    assert_ticket_id(page, "INC-1001")
    assert by_testid(page, ROLE).inner_text() == "l1"
