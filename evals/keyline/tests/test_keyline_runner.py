from keyline.load import load_task_by_id, load_tasks
from keyline.runner import load_tasks as runner_load_tasks

EXPECTED_IDS = [
    "kl-01-login-l1",
    "kl-02-login-admin-queue",
    "kl-03-list-queue",
    "kl-04-detail",
    "kl-05-iso-clarify",
    "kl-06-iso-investigate",
    "kl-07-iso-timeout",
    "kl-08-iso-reject",
    "kl-09-iso-l1-tool-deny",
    "kl-10-bypass-approval",
    "kl-11-fake-admin-copy",
    "kl-12-query-role",
    "kl-13-l1-open-approve",
    "kl-14-idempotent-ui",
    "kl-15-low-risk-comment",
]


def test_keyline_package_imports() -> None:
    import keyline

    assert keyline.__doc__
    tasks = load_tasks()
    ids = [item["id"] for item in tasks]
    assert ids == EXPECTED_IDS
    assert [item["id"] for item in runner_load_tasks()] == ids
    loaded = load_task_by_id("kl-12-query-role")
    assert loaded["expect_privilege_fail"] is True
    assert "db" in loaded["expect"]
