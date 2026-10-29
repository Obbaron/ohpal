"""Per-build UI state (grid layout + derived columns + removed columns).

Saved as a small JSON file in the build's cache dir (like the legacy
``.ampm-ui.json``), so a user's column order / hidden set / widths, their derived
columns and their removed columns persist per build and travel with its cache.
The grid header is a base64 blob from ``QHeaderView.saveState()``; derivations
and the removed list are stored as-is (plain dicts / strings).

The schema is additive: an older file that holds only ``grid_header`` still
loads (the other keys default to empty).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

_FILENAME = "grid_ui.json"
_VERSION = 1


def _path(cache_dir: Path) -> Path:
    return Path(cache_dir) / _FILENAME


def _empty() -> dict:
    return {"grid_header": None, "derivations": [], "removed": [], "filters": []}


def load_state(cache_dir: Path) -> dict:
    """Return {"grid_header": bytes|None, "derivations": list, "removed": list}."""
    try:
        data = json.loads(_path(cache_dir).read_text(encoding="utf-8"))
        if data.get("version") != _VERSION:
            return _empty()
        blob = data.get("grid_header")
        return {
            "grid_header": base64.b64decode(blob) if blob else None,
            "derivations": data.get("derivations") or [],
            "removed": data.get("removed") or [],
            "filters": data.get("filters") or [],
        }
    except (OSError, ValueError, KeyError):
        return _empty()


def clear(cache_dir: Path) -> None:
    """Delete the per-build UI state (used when a build is rebuilt fresh)."""
    try:
        _path(Path(cache_dir)).unlink(missing_ok=True)
    except OSError:
        pass


def save_state(
    cache_dir: Path,
    *,
    grid_header: bytes | None = None,
    derivations: list | None = None,
    removed: list | None = None,
    filters: list | None = None,
) -> None:
    """Write the full UI state. Best-effort — never blocks on failure."""
    try:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": _VERSION,
            "grid_header": (
                base64.b64encode(bytes(grid_header)).decode("ascii")
                if grid_header
                else None
            ),
            "derivations": list(derivations or []),
            "removed": list(removed or []),
            "filters": list(filters or []),
        }
        _path(cache_dir).write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        pass  # persistence is best-effort; never block on it
