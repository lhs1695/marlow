"""Orchestrate YAML load, Playwright solver, and DB scorer."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from keyline.db_scorer import (
    ApprovalSnap,
    EntitlementSnap,
    ScoreResult,
    score_task,
    snapshot_approvals,
    snapshot_entitlements,
)
from keyline.load import load_task_by_id, load_tasks
from keyline.playwright_solver import solve_task
from marlow.seed import ADMIN_ID, L1_ID

_ROLE_ACTOR = {"l1": L1_ID, "admin": ADMIN_ID}
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"


def evaluate_task(
    task: dict[str, Any],
    session: Session,
    *,
    baseline_entitlements: EntitlementSnap,
    baseline_approvals: ApprovalSnap,
    dom_ok: bool | None,
) -> ScoreResult:
    expect = task.get("expect")
    if not isinstance(expect, dict) or "db" not in expect:
        return ScoreResult(
            passed=False,
            db_ok=False,
            dom_ok=dom_ok,
            reasons=("missing db expect",),
        )
    db_expect = expect["db"] or {}
    actor_id = _ROLE_ACTOR[task["login_role"]]
    expected_role = db_expect.get("session_role") or task["login_role"]
    return score_task(
        session,
        actor_id=actor_id,
        expected_session_role=expected_role,
        expect_privilege_fail=bool(task["expect_privilege_fail"]),
        baseline_entitlements=baseline_entitlements,
        baseline_approvals=baseline_approvals,
        dom_ok=dom_ok,
    )


def run_task(task: dict[str, Any], page: Any, base_url: str, engine: Engine) -> ScoreResult:
    with Session(engine) as db:
        baseline_entitlements = snapshot_entitlements(db)
        baseline_approvals = snapshot_approvals(db)
    dom_ok = True
    try:
        solve_task(page, base_url, task)
    except Exception:
        dom_ok = False
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(ARTIFACTS / f"{task['id']}.png"))
        raise
    with Session(engine) as db:
        return evaluate_task(
            task,
            db,
            baseline_entitlements=baseline_entitlements,
            baseline_approvals=baseline_approvals,
            dom_ok=dom_ok,
        )


__all__ = ["evaluate_task", "load_task_by_id", "load_tasks", "run_task"]
