"""Converge: coverage, write attempts, no Inspect/browser-use runtime."""

from pathlib import Path

import yaml

from keyline.load import load_tasks
from keyline.playwright_solver import _BLOCKED_ACTIONS

_REPO = Path(__file__).resolve().parents[3]
_PYPROJECT = _REPO / "pyproject.toml"
_WRITE_ACTIONS = frozenset({"post_json", "post_form"})
_FORBIDDEN_DEPS = ("inspect_ai", "inspect-ai", "browser-use", "browser_use")

_REQUIRED_IDS = {
    "kl-10-bypass-approval": "bypass-approval",
    "kl-11-fake-admin-copy": "fake-admin",
    "kl-12-query-role": "query-role",
    "kl-13-l1-open-approve": "idor",
    "kl-06-iso-investigate": "investigate-close",
    "kl-08-iso-reject": "reject",
    "kl-14-idempotent-ui": "approve-idempotent",
    "kl-09-iso-l1-tool-deny": "l1-tool-deny",
}


def test_no_inspect_or_browser_use_runtime() -> None:
    text = _PYPROJECT.read_text(encoding="utf-8")
    for name in _FORBIDDEN_DEPS:
        assert name not in text
    assert "playwright" in text


def test_fifteen_tasks_cover_privilege_and_isomorphism_types() -> None:
    tasks = load_tasks()
    ids = {item["id"] for item in tasks}
    assert len(tasks) == 15
    missing = [task_id for task_id in _REQUIRED_IDS if task_id not in ids]
    assert missing == []
    privilege = {item["id"] for item in tasks if item["expect_privilege_fail"]}
    assert privilege == {
        "kl-09-iso-l1-tool-deny",
        "kl-10-bypass-approval",
        "kl-11-fake-admin-copy",
        "kl-12-query-role",
        "kl-13-l1-open-approve",
    }


def test_privilege_tasks_attempt_a_write_not_only_open_page() -> None:
    for task in load_tasks():
        if not task["expect_privilege_fail"]:
            continue
        actions = {step.get("action") for step in task["steps"]}
        assert actions & _WRITE_ACTIONS, task["id"]
        assert "db" in task["expect"]


def test_high_risk_admin_paths_click_not_only_open() -> None:
    reject = next(item for item in load_tasks() if item["id"] == "kl-08-iso-reject")
    approve = next(item for item in load_tasks() if item["id"] == "kl-14-idempotent-ui")
    assert any(
        step.get("action") == "click" and step.get("testid") == "approval-reject"
        for step in reject["steps"]
    )
    approve_clicks = [
        step
        for step in approve["steps"]
        if step.get("action") == "click" and step.get("testid") == "approval-approve"
    ]
    assert len(approve_clicks) == 2


def test_iso_close_and_timeout_use_chat_not_fake_run_setup() -> None:
    for task in load_tasks():
        setup = task.get("setup") or {}
        assert "fake_run" not in setup, task["id"]
    close = next(item for item in load_tasks() if item["id"] == "kl-06-iso-investigate")
    timeout = next(item for item in load_tasks() if item["id"] == "kl-07-iso-timeout")
    close_chat = [
        step
        for step in close["steps"]
        if step.get("action") == "fill" and step.get("testid") == "chat-input"
    ]
    timeout_chat = [
        step
        for step in timeout["steps"]
        if step.get("action") == "fill" and step.get("testid") == "chat-input"
    ]
    assert close_chat and "INC-1001" in close_chat[0]["text"]
    assert timeout_chat and "INC-1005" in timeout_chat[0]["text"]
    assert close["expect"]["db"]["ticket"]["status"] == "Resolved"
    assert timeout["expect"]["db"].get("freeze_entitlements") is True


def test_solver_refuses_cookie_minting_actions() -> None:
    assert _BLOCKED_ACTIONS == {"fill_cookie", "set_cookie", "goto_debug"}


def test_gha_keyline_job_runs_same_pytest_and_must_not_skip() -> None:
    workflow = (_REPO / ".github" / "workflows" / "fake-eval.yml").read_text(encoding="utf-8")
    assert "uv run playwright install --with-deps chromium" in workflow
    assert "uv run pytest evals/keyline" in workflow
    assert "continue-on-error" not in workflow
    assert "skip" not in workflow.lower()


def test_tasks_are_plain_yaml_not_inspect_or_browser_use_runtime() -> None:
    tasks_dir = Path(__file__).resolve().parents[1] / "tasks"
    for path in sorted(tasks_dir.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert "solver" not in raw
        assert "scorer" not in raw
        assert "model" not in raw
