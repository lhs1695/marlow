"""Human-readable labels for HTML. Testids still carry English domain strings."""

from __future__ import annotations

from marlow.codes import (
    QUEUE_CHANGE,
    QUEUE_L1,
    ROLE_ADMIN,
    ROLE_L1,
    RUN_ADMITTED,
    RUN_CANCELLED,
    RUN_COMPLETED,
    RUN_CREATED,
    RUN_FAILED,
    RUN_RUNNING,
    RUN_WAITING_APPROVAL,
    RUN_WAITING_TOOL,
    STATUS_INVESTIGATING,
    STATUS_NEW,
    STATUS_REJECTED,
    STATUS_RESOLVED,
    STATUS_WAITING_APPROVAL,
)

ROLE_ZH = {ROLE_L1: "一线", ROLE_ADMIN: "管理员"}
QUEUE_ZH = {QUEUE_L1: "一线", QUEUE_CHANGE: "变更"}
STATUS_ZH = {
    STATUS_NEW: "新建",
    STATUS_INVESTIGATING: "调查中",
    STATUS_WAITING_APPROVAL: "待审批",
    STATUS_RESOLVED: "已解决",
    STATUS_REJECTED: "已拒绝",
}
RUN_STATUS_ZH = {
    RUN_CREATED: "已创建",
    RUN_ADMITTED: "已受理",
    RUN_RUNNING: "处理中",
    RUN_WAITING_TOOL: "等待工具",
    RUN_WAITING_APPROVAL: "等待审批",
    RUN_COMPLETED: "已完成",
    RUN_FAILED: "已失败",
    RUN_CANCELLED: "已取消",
}


def role_zh(role: str) -> str:
    return ROLE_ZH.get(role, role)


def queue_zh(queue: str) -> str:
    return QUEUE_ZH.get(queue, queue)


def status_zh(status: str) -> str:
    return STATUS_ZH.get(status, status)


def run_status_zh(status: str) -> str:
    return RUN_STATUS_ZH.get(status, status or "")


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
