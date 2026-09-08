from marlow.codes import (
    DECISION_APPROVE,
    KB_MISS,
    NON_RETRYABLE,
    PERM_EDITOR,
    PERM_VIEWER,
    QUEUE_CHANGE,
    QUEUE_L1,
    RETRYABLE_TIMEOUT,
    SYSTEM_GRAFANA,
    TICKET_NOT_FOUND,
    UNAUTHORIZED,
)
from marlow.faults import FAULT_HTTP_200_BUSINESS_FAIL, FAULT_TIMEOUT, FaultHooks
from marlow.gateway import entitlement_permission
from marlow.observation import Observation
from marlow.seed import ADMIN_ID, INJECTION_COMMENT, L1_ID
from marlow.tools import (
    TOOL_NAMES,
    execute_tool,
    get_asset,
    get_ticket,
    search_kb,
    search_tickets,
)


def test_observation_cannot_be_trusted() -> None:
    obs = Observation(ok=True, code="ok", retryable=False, untrusted=False)
    assert obs.untrusted is True


def test_get_ticket_missing_is_not_retryable(session) -> None:
    obs = get_ticket(session, actor_id=L1_ID, ticket_id="INC-9999")
    assert obs.ok is False
    assert obs.code == TICKET_NOT_FOUND
    assert obs.retryable is False
    assert obs.untrusted is True


def test_search_tickets_filters_by_role_and_queue(session) -> None:
    l1 = search_tickets(session, actor_id=L1_ID, query="")
    assert l1.ok is True
    assert l1.untrusted is True
    l1_ids = {row["id"] for row in l1.data["tickets"]}
    l1_queues = {row["queue"] for row in l1.data["tickets"]}
    assert QUEUE_CHANGE not in l1_queues
    assert l1_queues == {QUEUE_L1}
    assert "CHG-2001" not in l1_ids
    assert "INC-1001" in l1_ids

    admin = search_tickets(session, actor_id=ADMIN_ID, query="")
    admin_ids = {row["id"] for row in admin.data["tickets"]}
    admin_queues = {row["queue"] for row in admin.data["tickets"]}
    assert QUEUE_CHANGE in admin_queues
    assert "CHG-2001" in admin_ids
    assert len(admin_ids) == 15


def test_l1_cannot_get_change_ticket(session) -> None:
    obs = get_ticket(session, actor_id=L1_ID, ticket_id="CHG-2001")
    assert obs.ok is False
    assert obs.code == UNAUTHORIZED


def test_get_ticket_comments_are_untrusted(session) -> None:
    obs = get_ticket(session, actor_id=L1_ID, ticket_id="INC-1010")
    assert obs.ok is True
    assert obs.untrusted is True
    bodies = [c["body"] for c in obs.data["comments"]]
    assert INJECTION_COMMENT in bodies


def test_get_asset_returns_config_and_owner(session) -> None:
    obs = get_asset(session, actor_id=L1_ID, asset_id="ast-grafana-prod")
    assert obs.ok is True
    assert obs.untrusted is True
    asset = obs.data["asset"]
    assert asset["owner_employee_id"] == ADMIN_ID
    assert "grafana.example.com" in asset["config"]


def test_search_kb_empty_and_fixture_carries_doc_id_version(session) -> None:
    miss = search_kb(query="coffee machine E7")
    assert miss.ok is False
    assert miss.code == KB_MISS
    assert miss.untrusted is True
    assert miss.data["hits"] == []

    hit = search_kb(query="grafana login")
    assert hit.ok is True
    assert hit.untrusted is True
    assert hit.data["hits"]
    for row in hit.data["hits"]:
        assert row["doc_id"]
        assert row["version"]


def test_add_comment_via_tool_is_untrusted(session) -> None:
    obs = execute_tool(
        session,
        "add_ticket_comment",
        actor_id=L1_ID,
        ticket_id="INC-1001",
        body="Checking login path.",
    )
    assert obs.ok is True
    assert obs.untrusted is True
    assert obs.data["body"] == "Checking login path."


def test_entitlement_change_tool_still_uses_gateway(session) -> None:
    before = entitlement_permission(session, "emp-007", SYSTEM_GRAFANA)
    assert before == PERM_VIEWER
    obs = execute_tool(
        session,
        "apply_entitlement_change",
        actor_id=L1_ID,
        ticket_id="CHG-2004",
        target_employee_id="emp-007",
        system=SYSTEM_GRAFANA,
        new_permission=PERM_EDITOR,
        decision=DECISION_APPROVE,
        idempotency_key="k-tool-l1",
    )
    session.flush()
    assert obs.ok is False
    assert obs.code == UNAUTHORIZED
    assert obs.untrusted is True
    assert entitlement_permission(session, "emp-007", SYSTEM_GRAFANA) == PERM_VIEWER


def test_fault_timeout_is_retryable(session) -> None:
    hooks = FaultHooks()
    hooks.set_target("get_asset", "ast-laptop-casey", FAULT_TIMEOUT)
    obs = execute_tool(
        session,
        "get_asset",
        actor_id=L1_ID,
        faults=hooks,
        asset_id="ast-laptop-casey",
    )
    assert obs.ok is False
    assert obs.code == RETRYABLE_TIMEOUT
    assert obs.retryable is True
    assert obs.untrusted is True


def test_fault_http_200_is_not_success(session) -> None:
    hooks = FaultHooks()
    hooks.set_tool("get_ticket", FAULT_HTTP_200_BUSINESS_FAIL)
    obs = execute_tool(
        session,
        "get_ticket",
        actor_id=L1_ID,
        faults=hooks,
        ticket_id="INC-1006",
    )
    assert obs.ok is False
    assert obs.code == NON_RETRYABLE
    assert obs.data["http_status"] == 200


def test_mcp_sdk_lists_six_tool_schemas() -> None:
    from marlow.ticket_mcp import list_tool_schemas

    schemas = list_tool_schemas()
    names = [row["name"] for row in schemas]
    assert tuple(names) == TOOL_NAMES
    for row in schemas:
        assert "properties" in row["parameters"]
