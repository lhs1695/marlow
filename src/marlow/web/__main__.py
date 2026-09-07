"""uvicorn entry: python -m marlow.web"""

from __future__ import annotations

import sys

from marlow.stdio import ensure_utf8_stdio


def main(argv: list[str] | None = None) -> int:
    ensure_utf8_stdio()
    import uvicorn

    host = "127.0.0.1"
    port = 8000
    args = argv if argv is not None else sys.argv[1:]
    if "--port" in args:
        idx = args.index("--port")
        port = int(args[idx + 1])
    uvicorn.run("marlow.web.app:create_app", factory=True, host=host, port=port, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
