"""Stable short codes and frozen domain strings."""

TICKET_NOT_FOUND = "ticket_not_found"
UNAUTHORIZED = "unauthorized"
APPROVAL_REJECTED = "approval_rejected"
IDEMPOTENT_REPLAY = "idempotent_replay"
OK = "ok"
KB_MISS = "kb_miss"
RETRYABLE_TIMEOUT = "retryable_timeout"
NON_RETRYABLE = "non_retryable"
NOT_ENOUGH_INFO = "not_enough_info"
MAX_STEPS = "max_steps"
APPROVAL_REQUIRED = "approval_required"

MAX_STEPS_LIMIT = 12
MAX_TOKENS_LIMIT = 50_000
MAX_COST_CENTS_LIMIT = 500
FAKE_TOKENS_PER_STEP = 200
FAKE_COST_CENTS_PER_STEP = 1

RUN_CREATED = "created"
RUN_ADMITTED = "admitted"
RUN_RUNNING = "running"
RUN_WAITING_TOOL = "waiting_tool"
RUN_WAITING_APPROVAL = "waiting_approval"
RUN_COMPLETED = "completed"
RUN_FAILED = "failed"
RUN_CANCELLED = "cancelled"

ACTION_ANSWER = "answer"
ACTION_SKILL = "skill"
ACTION_TOOL = "tool"

SKILL_ENTITLEMENT_CHANGE = "entitlement_change"

ROLE_L1 = "l1"
ROLE_ADMIN = "admin"
ROLE_REQUESTER = "requester"

QUEUE_L1 = "it-l1"
QUEUE_CHANGE = "it-change"

STATUS_NEW = "New"
STATUS_INVESTIGATING = "Investigating"
STATUS_WAITING_APPROVAL = "Waiting for approval"
STATUS_RESOLVED = "Resolved"
STATUS_REJECTED = "Rejected"

DECISION_APPROVE = "approve"
DECISION_REJECT = "reject"

SYSTEM_GRAFANA = "grafana"
PERM_VIEWER = "Viewer"
PERM_EDITOR = "Editor"
PERM_ADMIN = "Admin"
