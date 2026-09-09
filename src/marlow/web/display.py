"""Human-readable labels for HTML. Testids still carry English domain strings."""

from __future__ import annotations

from marlow.codes import (
    QUEUE_CHANGE,
    QUEUE_L1,
    ROLE_ADMIN,
    ROLE_L1,
    STATUS_INVESTIGATING,
    STATUS_NEW,
    STATUS_REJECTED,
    STATUS_RESOLVED,
    STATUS_WAITING_APPROVAL,
)

ROLE_ZH = {ROLE_L1: "一线", ROLE_ADMIN: "管理员"}
QUEUE_ZH = {QUEUE_L1: "一线队列", QUEUE_CHANGE: "变更队列"}
STATUS_ZH = {
    STATUS_NEW: "新建",
    STATUS_INVESTIGATING: "调查中",
    STATUS_WAITING_APPROVAL: "待审批",
    STATUS_RESOLVED: "已解决",
    STATUS_REJECTED: "已拒绝",
}
DEMO_FOCUS_IDS = frozenset({"INC-1001", "INC-1005", "CHG-2003", "CHG-2004"})


def role_zh(role: str) -> str:
    return ROLE_ZH.get(role, role)


def queue_zh(queue: str) -> str:
    return QUEUE_ZH.get(queue, queue)


def status_zh(status: str) -> str:
    return STATUS_ZH.get(status, status)


def status_tone(status: str) -> str:
    if status == STATUS_RESOLVED:
        return "ok"
    if status == STATUS_REJECTED:
        return "bad"
    if status == STATUS_WAITING_APPROVAL:
        return "wait"
    if status == STATUS_INVESTIGATING:
        return "progress"
    return "new"


def show_change_decisions(*, role: str, queue: str, status: str) -> bool:
    """Admin change tickets except seeded New (IDOR vehicle) keep approve/reject for idempotent retries."""
    return role == ROLE_ADMIN and queue == QUEUE_CHANGE and status != STATUS_NEW
