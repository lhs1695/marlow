"""uvicorn entry: python -m marlow.web"""

from __future__ import annotations

import os
import sys

from marlow.credentials import load_local_env
from marlow.stdio import ensure_utf8_stdio

WEB_HOST_ENV = "MARLOW_WEB_HOST"
WEB_PORT_ENV = "MARLOW_WEB_PORT"
CHROMA_DIR_ENV = "MARLOW_CHROMA_DIR"


def _prepare_chroma() -> None:
    persist = os.environ.get(CHROMA_DIR_ENV, "").strip()
    if not persist:
        return
    from marlow.kb.store import ensure_chroma_dir

    ensure_chroma_dir(persist)


def main(argv: list[str] | None = None) -> int:
    ensure_utf8_stdio()
    load_local_env()
    import uvicorn

    host = os.environ.get(WEB_HOST_ENV, "127.0.0.1").strip() or "127.0.0.1"
    port = int(os.environ.get(WEB_PORT_ENV, "8000") or "8000")
    args = argv if argv is not None else sys.argv[1:]
    if "--host" in args:
        host = args[args.index("--host") + 1]
    if "--port" in args:
        port = int(args[args.index("--port") + 1])
    _prepare_chroma()
    uvicorn.run("marlow.web.app:create_app", factory=True, host=host, port=port, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
