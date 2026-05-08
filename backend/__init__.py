"""Resell Copilot backend package.

Adds the repo's `models/` and `src/` directories to ``sys.path`` so backend
modules can import `train_*_head`, `extract_features`, `build_price_dataset`,
and `prompts` without dotted package paths. Centralised here so submodules
don't each repeat the hack.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
for _sub in ("models", "src"):
    _path = str(_REPO_ROOT / _sub)
    if _path not in sys.path:
        sys.path.insert(0, _path)
