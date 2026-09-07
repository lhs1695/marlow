"""Force UTF-8 stdio on Windows so Chinese is not garbled in the terminal."""

from __future__ import annotations

import os
import sys
from typing import TextIO

_UTF8 = "utf-8"


def ensure_utf8_stdio() -> None:
    """Make stdin/stdout/stderr UTF-8 and set the console code page to 65001.

    Safe to call more than once. Does not replace streams (pytest capsys stays intact).
    """
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"
    os.environ.pop("PYTHONLEGACYWINDOWSSTDIO", None)
    _configure_windows_console()
    _reconfigure(sys.stdin)
    _reconfigure(sys.stdout)
    _reconfigure(sys.stderr)


def _reconfigure(stream: TextIO | None) -> None:
    if stream is None:
        return
    reconfigure = getattr(stream, "reconfigure", None)
    if not callable(reconfigure):
        return
    try:
        reconfigure(encoding=_UTF8, errors="replace")
    except (OSError, ValueError, AttributeError, TypeError):
        return


def _configure_windows_console() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
    except ImportError:
        return
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleOutputCP(65001)
        kernel32.SetConsoleCP(65001)
    except (AttributeError, OSError, ValueError):
        return
