"""Playwright solver: click testids, never mint session tokens."""

from __future__ import annotations

from playwright.sync_api import Page, expect

from marlow.web.testids import (
    APPROVAL_QUEUE,
    LOGIN_ADMIN,
    LOGIN_L1,
    ROLE,
    TICKET_ID,
    TICKET_LIST,
)

_LOGIN_TESTID = {"l1": LOGIN_L1, "admin": LOGIN_ADMIN}


def by_testid(page: Page, testid: str):
    return page.get_by_test_id(testid)


def login(page: Page, base_url: str, login_role: str) -> None:
    testid = _LOGIN_TESTID.get(login_role)
    if testid is None:
        raise ValueError(f"unknown login_role={login_role!r}")
    page.goto(f"{base_url}/")
    by_testid(page, testid).click()
    page.wait_for_url("**/tickets")
    expect(by_testid(page, ROLE)).to_have_text(login_role)


def open_path(page: Page, base_url: str, path: str) -> None:
    page.goto(f"{base_url}{path}")


def assert_role(page: Page, login_role: str) -> None:
    expect(by_testid(page, ROLE)).to_have_text(login_role)


def assert_ticket_list(page: Page) -> None:
    expect(by_testid(page, TICKET_LIST)).to_be_visible()


def assert_approval_queue(page: Page) -> None:
    expect(by_testid(page, APPROVAL_QUEUE)).to_be_visible()


def assert_ticket_id(page: Page, ticket_id: str) -> None:
    expect(by_testid(page, TICKET_ID)).to_have_text(ticket_id)
