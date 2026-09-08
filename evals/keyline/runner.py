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
    extra_db_reasons,
    score_task,
    snapshot_approvals,
    snapshot_comment_count,
    snapshot_entitlements,
)
from keyline.load import load_task_by_id, load_tasks
from keyline.playwright_solver import solve_task
from marlow.engine import start_run
from marlow.fake import provider_for_case
from marlow.seed import ADMIN_ID, L1_ID

_ROLE_ACTOR = {"l1": L1_ID, "admin": ADMIN_ID}
ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
LAST_RUN = Path(__file__).resolve().parent / "last_run.md"
TASK_REPORT: list[tuple[str, bool | None, bool]] = []


def evaluate_task(
    task: dict[str, Any],
    session: Session,
    *,
    baseline_entitlements: EntitlementSnap,
    baseline_approvals: ApprovalSnap,
    baseline_comments: int = 0,
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
    priv = bool(task["expect_privilege_fail"])
    extras = extra_db_reasons(session, db_expect, baseline_comments=baseline_comments)
    return score_task(
        session,
        actor_id=actor_id,
        expected_session_role=expected_role,
        expect_privilege_fail=priv,
        baseline_entitlements=baseline_entitlements,
        baseline_approvals=baseline_approvals,
        freeze_entitlements=True if priv else db_expect.get("freeze_entitlements"),
        freeze_approvals=True if priv else db_expect.get("freeze_approvals"),
        extra_reasons=tuple(extras),
        dom_ok=dom_ok,
    )


def _apply_setup(engine: Engine, task: dict[str, Any]) -> None:
    fake = (task.get("setup") or {}).get("fake_run")
    if not fake:
        return
    with Session(engine) as db:
        start_run(
            db,
            actor_id=_ROLE_ACTOR[task["login_role"]],
            user_text=fake["user_text"],
            case_id=fake["case_id"],
            provider=provider_for_case(fake["case_id"]),
        )
        db.commit()


def run_task(task: dict[str, Any], page: Any, base_url: str, engine: Engine) -> ScoreResult:
    _apply_setup(engine, task)
    with Session(engine) as db:
        baseline_entitlements = snapshot_entitlements(db)
        baseline_approvals = snapshot_approvals(db)
        baseline_comments = snapshot_comment_count(db)
    dom_ok = True
    try:
        solve_task(page, base_url, task)
    except Exception:
        dom_ok = False
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(ARTIFACTS / f"{task['id']}.png"))
        raise
    with Session(engine) as db:
        result = evaluate_task(
            task,
            db,
            baseline_entitlements=baseline_entitlements,
            baseline_approvals=baseline_approvals,
            baseline_comments=baseline_comments,
            dom_ok=dom_ok,
        )
    TASK_REPORT.append((task["id"], result.dom_ok, result.db_ok))
    return result


def write_last_run(path: Path | None = None) -> None:
    dest = path or LAST_RUN
    lines = [
        "# Keyline last run",
        "",
        "| id | dom | db |",
        "| --- | --- | --- |",
    ]
    for task_id, dom_ok, db_ok in TASK_REPORT:
        lines.append(f"| {task_id} | {dom_ok} | {db_ok} |")
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")


__all__ = ["evaluate_task", "load_task_by_id", "load_tasks", "run_task", "write_last_run"]
