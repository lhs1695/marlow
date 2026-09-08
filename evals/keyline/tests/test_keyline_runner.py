from keyline.load import load_task_by_id, load_tasks
from keyline.runner import load_tasks as runner_load_tasks


def test_keyline_package_imports() -> None:
    import keyline

    assert keyline.__doc__
    tasks = load_tasks()
    ids = [item["id"] for item in tasks]
    assert ids == [
        "kl-10-bypass-approval",
        "kl-11-fake-admin-copy",
        "kl-12-query-role",
        "kl-13-l1-open-approve",
    ]
    assert [item["id"] for item in runner_load_tasks()] == ids
    loaded = load_task_by_id("kl-12-query-role")
    assert loaded["expect_privilege_fail"] is True
    assert "db" in loaded["expect"]
