import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from marlow.codes import PERM_EDITOR, PERM_VIEWER, SYSTEM_GRAFANA
from marlow.models import Entitlement

from keyline.db_scorer import snapshot_approvals, snapshot_entitlements
from keyline.load import load_task_by_id
from keyline.runner import evaluate_task, run_task


def test_missing_db_expect_fails_task(session) -> None:
    task = load_task_by_id("kl-12-query-role")
    task = {**task, "expect": {"dom": [{"testid": "role", "text": "l1"}]}}
    result = evaluate_task(
        task,
        session,
        baseline_entitlements=snapshot_entitlements(session),
        baseline_approvals=snapshot_approvals(session),
        dom_ok=True,
    )
    assert result.dom_ok is True
    assert result.db_ok is False
    assert result.passed is False
    assert "missing db expect" in result.reasons


def test_dom_ok_but_entitlements_changed_fails_task(session) -> None:
    task = load_task_by_id("kl-12-query-role")
    baseline_entitlements = snapshot_entitlements(session)
    baseline_approvals = snapshot_approvals(session)
    row = session.scalar(
        select(Entitlement).where(
            Entitlement.employee_id == "emp-007",
            Entitlement.system == SYSTEM_GRAFANA,
        )
    )
    assert row is not None
    row.permission = PERM_EDITOR
    session.flush()
    result = evaluate_task(
        task,
        session,
        baseline_entitlements=baseline_entitlements,
        baseline_approvals=baseline_approvals,
        dom_ok=True,
    )
    assert result.dom_ok is True
    assert result.db_ok is False
    assert result.passed is False
    assert "entitlements changed" in result.reasons


@pytest.mark.parametrize("task_id", ["kl-12-query-role"])
def test_yaml_task_e2e(live_app, page, task_id: str) -> None:
    task = load_task_by_id(task_id)
    result = run_task(task, page, live_app["base_url"], live_app["engine"])
    assert result.dom_ok is True
    assert result.db_ok is True
    assert result.passed is True
    with Session(live_app["engine"]) as db:
        permission = db.scalar(
            select(Entitlement.permission).where(
                Entitlement.employee_id == "emp-007",
                Entitlement.system == SYSTEM_GRAFANA,
            )
        )
        assert permission == PERM_VIEWER
