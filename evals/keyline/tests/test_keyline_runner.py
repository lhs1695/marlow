from pathlib import Path

from keyline.load import load_task_by_id, load_tasks
from keyline.runner import load_tasks as runner_load_tasks
from keyline.runner import write_last_run

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


def test_last_run_marks_privilege_intercept_rows(tmp_path: Path) -> None:
    dest = tmp_path / "last_run.md"
    text = write_last_run(
        dest,
        rows=[
            ("kl-01-login-l1", True, True, False),
            ("kl-09-iso-l1-tool-deny", True, True, True),
            ("kl-12-query-role", True, False, True),
        ],
    )
    assert "| id | privilege_fail | dom | db |" in text
    assert "| kl-01-login-l1 | no | True | True |" in text
    assert "| kl-09-iso-l1-tool-deny | yes | True | True |" in text
    assert "| kl-12-query-role | yes | True | False |" in text
    assert dest.read_text(encoding="utf-8") == text
    intercept = [
        item["id"] for item in load_tasks() if item["expect_privilege_fail"]
    ]
    assert intercept == [
        "kl-09-iso-l1-tool-deny",
        "kl-10-bypass-approval",
        "kl-11-fake-admin-copy",
        "kl-12-query-role",
        "kl-13-l1-open-approve",
    ]
