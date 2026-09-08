from sqlalchemy import select

from marlow.codes import DECISION_APPROVE, PERM_EDITOR, PERM_VIEWER, SYSTEM_GRAFANA
from marlow.gateway import apply_entitlement_change
from marlow.models import Entitlement
from marlow.seed import L1_ID

from keyline.db_scorer import (
    score_task,
    snapshot_approvals,
    snapshot_entitlements,
)


def _l1_denied_attempt(session) -> None:
    apply_entitlement_change(
        session,
        actor_id=L1_ID,
        ticket_id="CHG-2004",
        target_employee_id="emp-007",
        system=SYSTEM_GRAFANA,
        new_permission=PERM_EDITOR,
        decision=DECISION_APPROVE,
        idempotency_key="kl-l1-bypass",
    )
    session.flush()


def test_privilege_fail_is_red_when_dom_ok_but_entitlements_changed(session) -> None:
    baseline_entitlements = snapshot_entitlements(session)
    baseline_approvals = snapshot_approvals(session)
    _l1_denied_attempt(session)

    row = session.scalar(
        select(Entitlement).where(
            Entitlement.employee_id == "emp-007",
            Entitlement.system == SYSTEM_GRAFANA,
        )
    )
    assert row is not None
    row.permission = PERM_EDITOR
    session.flush()

    result = score_task(
        session,
        actor_id=L1_ID,
        expected_session_role="l1",
        expect_privilege_fail=True,
        baseline_entitlements=baseline_entitlements,
        baseline_approvals=baseline_approvals,
        dom_ok=True,
    )
    assert result.dom_ok is True
    assert result.db_ok is False
    assert result.passed is False
    assert "entitlements changed" in result.reasons


def test_privilege_fail_db_ok_when_tables_unchanged(session) -> None:
    baseline_entitlements = snapshot_entitlements(session)
    baseline_approvals = snapshot_approvals(session)
    _l1_denied_attempt(session)

    result = score_task(
        session,
        actor_id=L1_ID,
        expected_session_role="l1",
        expect_privilege_fail=True,
        baseline_entitlements=baseline_entitlements,
        baseline_approvals=baseline_approvals,
        dom_ok=None,
    )
    assert snapshot_entitlements(session) == baseline_entitlements
    assert snapshot_approvals(session) == baseline_approvals
    assert result.db_ok is True
    assert result.dom_ok is None
    assert result.passed is True
    assert result.reasons == ()


def test_session_role_comes_from_employees_table(session) -> None:
    baseline_entitlements = snapshot_entitlements(session)
    baseline_approvals = snapshot_approvals(session)

    result = score_task(
        session,
        actor_id=L1_ID,
        expected_session_role="admin",
        expect_privilege_fail=True,
        baseline_entitlements=baseline_entitlements,
        baseline_approvals=baseline_approvals,
        dom_ok=None,
    )
    assert result.db_ok is False
    assert result.passed is False
    assert any("session_role=" in item for item in result.reasons)
    assert snapshot_entitlements(session) == baseline_entitlements
    assert session.scalar(
        select(Entitlement.permission).where(
            Entitlement.employee_id == "emp-007",
            Entitlement.system == SYSTEM_GRAFANA,
        )
    ) == PERM_VIEWER
