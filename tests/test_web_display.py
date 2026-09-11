from marlow.codes import (
    QUEUE_CHANGE,
    QUEUE_L1,
    ROLE_ADMIN,
    ROLE_L1,
    RUN_COMPLETED,
    RUN_RUNNING,
    RUN_WAITING_APPROVAL,
    STATUS_NEW,
    STATUS_WAITING_APPROVAL,
)
from marlow.web.display import run_status_zh, show_change_decisions, status_tone, status_zh


def test_show_change_decisions_skips_seeded_new() -> None:
    assert not show_change_decisions(role=ROLE_ADMIN, queue=QUEUE_CHANGE, status=STATUS_NEW)
    assert show_change_decisions(
        role=ROLE_ADMIN, queue=QUEUE_CHANGE, status=STATUS_WAITING_APPROVAL
    )
    assert not show_change_decisions(
        role=ROLE_L1, queue=QUEUE_CHANGE, status=STATUS_WAITING_APPROVAL
    )
    assert not show_change_decisions(
        role=ROLE_ADMIN, queue=QUEUE_L1, status=STATUS_WAITING_APPROVAL
    )


def test_status_labels() -> None:
    assert status_zh(STATUS_WAITING_APPROVAL) == "待审批"
    assert status_tone("Resolved") == "ok"
    assert run_status_zh(RUN_RUNNING) == "处理中"
    assert run_status_zh(RUN_WAITING_APPROVAL) == "等待审批"
    assert run_status_zh(RUN_COMPLETED) == "已完成"
