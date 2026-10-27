"""Per-build UI state (grid column layout).

Saved as a small JSON file in the build's cache dir (like the legacy
``.ampm-ui.json``), so a user's column order / hidden set / widths persist per
build and travel with its cache. The grid header is stored as a base64 blob
from ``QHeaderView.saveState()``.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

_FILENAME = "grid_ui.json"
_VERSION = 1


def _path(cache_dir: Path) -> Path:
    return Path(cache_dir) / _FILENAME


def load_grid_header(cache_dir: Path) -> bytes | None:
    try:
        data = json.loads(_path(cache_dir).read_text(encoding="utf-8"))
        if data.get("version") != _VERSION:
            return None
        blob = data.get("grid_header")
        return base64.b64decode(blob) if blob else None
    except (OSError, ValueError, KeyError):
        return None


def save_grid_header(cache_dir: Path, state: bytes) -> None:
    try:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": _VERSION,
            "grid_header": base64.b64encode(bytes(state)).decode("ascii"),
        }
        _path(cache_dir).write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        pass  # persistence is best-effort; never block on it
