"""Put `evals/` on sys.path so `import keyline` works under pytest."""

from __future__ import annotations

import sys
from pathlib import Path

_evals_dir = Path(__file__).resolve().parent.parent
_evals_str = str(_evals_dir)
if _evals_str not in sys.path:
    sys.path.insert(0, _evals_str)
