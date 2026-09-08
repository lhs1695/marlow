"""Put `evals/` on sys.path so `import keyline` works under pytest."""

from __future__ import annotations

import socket
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from marlow.db import make_engine, prepare_database
from marlow.web.app import create_app

_evals_dir = Path(__file__).resolve().parent.parent
_evals_str = str(_evals_dir)
if _evals_str not in sys.path:
    sys.path.insert(0, _evals_str)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def session() -> Iterator[Session]:
    engine = make_engine("sqlite:///:memory:")
    prepare_database(engine)
    with Session(engine) as db:
        yield db


@pytest.fixture
def live_app() -> Iterator[dict[str, Any]]:
    import uvicorn

    engine = make_engine("sqlite:///:memory:")
    prepare_database(engine)
    app = create_app(engine)
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not server.started:
        if time.time() > deadline:
            raise RuntimeError("uvicorn did not start")
        time.sleep(0.05)
    yield {"base_url": f"http://127.0.0.1:{port}", "engine": engine}
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="module")
def chromium_browser() -> Iterator[Any]:
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def page(chromium_browser: Any) -> Iterator[Any]:
    context = chromium_browser.new_context()
    page = context.new_page()
    yield page
    context.close()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    from keyline.runner import TASK_REPORT, write_last_run

    if TASK_REPORT:
        write_last_run()
