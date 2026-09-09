"""Playwright solver: click testids, never mint session tokens."""

from __future__ import annotations

import json
from typing import Any

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
_BLOCKED_ACTIONS = {"fill_cookie", "set_cookie", "goto_debug"}


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


def _assert_dom_item(page: Page, item: dict[str, Any]) -> None:
    loc = by_testid(page, item["testid"])
    if item.get("visible") is False:
        expect(loc).to_have_count(0)
        return
    if "text" in item:
        expect(loc).to_have_text(item["text"])
        return
    if "contains" in item:
        expect(loc).to_contain_text(item["contains"])
        return
    expect(loc).to_be_visible()


def _corrupt_session_cookie(page: Page) -> None:
    cookies = page.context.cookies()
    session_cookies = [cookie for cookie in cookies if cookie.get("name") == "session"]
    if not session_cookies:
        raise AssertionError("no session cookie to corrupt")
    cookie = dict(session_cookies[0])
    cookie["value"] = str(cookie.get("value") or "") + "x"
    page.context.add_cookies([cookie])


def solve_task(page: Page, base_url: str, task: dict[str, Any]) -> None:
    login(page, base_url, task["login_role"])
    start = task.get("start_path")
    if start:
        open_path(page, base_url, start)
    for step in task.get("steps") or []:
        _run_step(page, base_url, step)
    expect_spec = task.get("expect") or {}
    url_contains = expect_spec.get("url_contains")
    if url_contains and url_contains not in page.url:
        raise AssertionError(f"url {page.url!r} missing {url_contains!r}")
    for item in expect_spec.get("dom") or []:
        _assert_dom_item(page, item)


def _run_step(page: Page, base_url: str, step: dict[str, Any]) -> None:
    action = step.get("action")
    if action in _BLOCKED_ACTIONS or action is None:
        raise ValueError(f"blocked or missing action: {action!r}")
    if action == "open":
        open_path(page, base_url, step["path"])
        return
    if action == "expect_testid":
        _assert_dom_item(page, step)
        return
    if action == "fill":
        by_testid(page, step["testid"]).fill(step["text"])
        return
    if action == "click":
        loc = by_testid(page, step["testid"])
        ticket_id = step.get("ticket_id")
        if ticket_id:
            loc = page.locator(
                f'[data-testid="approval-item"][data-ticket-id="{ticket_id}"]'
            ).get_by_test_id(step["testid"])
        loc.click()
        page.wait_for_load_state("load")
        return
    if action == "expect_absent_text":
        body = page.content()
        for snippet in step.get("texts") or []:
            if snippet in body:
                raise AssertionError(f"unexpected text {snippet!r}")
        return
    if action == "get":
        response = page.request.get(f"{base_url}{step['path']}")
        expected = int(step.get("expect_status", 200))
        if response.status != expected:
            raise AssertionError(
                f"GET {step['path']} status {response.status} expected {expected}"
            )
        return
    if action == "corrupt_session_cookie":
        _corrupt_session_cookie(page)
        return
    if action == "post_json":
        response = page.request.post(
            f"{base_url}{step['path']}",
            headers={"content-type": "application/json"},
            data=json.dumps(step["json"]),
        )
        expected = int(step.get("expect_status", 403))
        if response.status != expected:
            raise AssertionError(
                f"POST {step['path']} status {response.status} expected {expected}"
            )
        return
    if action == "post_form":
        response = page.request.post(f"{base_url}{step['path']}", form=step["form"])
        expected = int(step.get("expect_status", 403))
        if response.status != expected:
            raise AssertionError(
                f"POST {step['path']} status {response.status} expected {expected}"
            )
        return
    raise ValueError(f"unknown action: {action!r}")
