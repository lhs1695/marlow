from keyline.load import load_task_by_id, load_tasks
from keyline.runner import load_tasks as runner_load_tasks


def test_keyline_package_imports() -> None:
    import keyline

    assert keyline.__doc__
    tasks = load_tasks()
    assert [item["id"] for item in tasks] == ["kl-12-query-role"]
    assert runner_load_tasks()[0]["id"] == "kl-12-query-role"
    loaded = load_task_by_id("kl-12-query-role")
    assert loaded["expect_privilege_fail"] is True
    assert "db" in loaded["expect"]
