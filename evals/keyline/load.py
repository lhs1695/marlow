"""Load Keyline YAML tasks. One file, one task."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

TASKS_DIR = Path(__file__).resolve().parent / "tasks"

_REQUIRED = ("id", "login_role", "start_path", "steps", "expect", "expect_privilege_fail")


def load_task(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"task is not a mapping: {path}")
    missing = [key for key in _REQUIRED if key not in raw]
    if missing:
        raise ValueError(f"{path.name} missing fields: {missing}")
    if raw["login_role"] not in {"l1", "admin"}:
        raise ValueError(f"bad login_role in {path.name}")
    return raw


def load_task_by_id(task_id: str, tasks_dir: Path | None = None) -> dict[str, Any]:
    directory = tasks_dir or TASKS_DIR
    path = directory / f"{task_id}.yaml"
    if not path.is_file():
        raise FileNotFoundError(path)
    task = load_task(path)
    if task["id"] != task_id:
        raise ValueError(f"{path.name} id {task['id']!r} != {task_id!r}")
    return task


def load_tasks(tasks_dir: Path | None = None) -> list[dict[str, Any]]:
    directory = tasks_dir or TASKS_DIR
    paths = sorted(directory.glob("*.yaml"))
    return [load_task(path) for path in paths]
