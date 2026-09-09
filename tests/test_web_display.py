from marlow.codes import QUEUE_CHANGE, QUEUE_L1, ROLE_ADMIN, ROLE_L1, STATUS_NEW, STATUS_WAITING_APPROVAL
from marlow.web.display import show_change_decisions, status_tone, status_zh


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
