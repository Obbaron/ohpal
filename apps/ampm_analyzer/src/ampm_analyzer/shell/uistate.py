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
    return {
        "grid_header": None, "derivations": [], "removed": [], "filters": [],
        "grid_columns": [], "grid_order": [], "grid_hidden": [],
        "part_method": "", "apply_mask": False, "correction": {}, "renames": {},
        "load_columns": [],
    }


def load_state(cache_dir: Path) -> dict:
    """Return the saved per-build UI state (missing keys default to empty)."""
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
            # Column names the header blob was saved with, plus order/hidden by
            # name — used to validate the blob and lay out by name when the
            # column set has drifted (a stale blob would corrupt the header).
            "grid_columns": data.get("grid_columns") or [],
            "grid_order": data.get("grid_order") or [],
            "grid_hidden": data.get("grid_hidden") or [],
            # The part-assignment method chosen in the setup form at build time.
            # config.toml doesn't record it, so it's persisted here and re-applied
            # on open (else a reopened cached build loses its part_id column).
            "part_method": data.get("part_method") or "",
            # Whether the Apply-mask toggle was on at build time. Like
            # part_method, config.toml doesn't record it, so it's persisted here
            # and re-applied on open (else a reopened build loses its masking).
            "apply_mask": bool(data.get("apply_mask")),
            # Correction recipe (on/machine/column/mode/output), also absent from
            # config.toml, persisted here and re-applied on open.
            "correction": data.get("correction") or {},
            # The source columns chosen at build time ([] = all). Not in
            # config.toml either; without it a reopened build loads every column.
            "load_columns": data.get("load_columns") or [],
            # Column renames: original datastore name -> current display name.
            "renames": data.get("renames") or {},
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
    grid_columns: list | None = None,
    grid_order: list | None = None,
    grid_hidden: list | None = None,
    part_method: str | None = None,
    apply_mask: bool | None = None,
    correction: dict | None = None,
    load_columns: list | None = None,
    renames: dict | None = None,
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
            "grid_columns": list(grid_columns or []),
            "grid_order": list(grid_order or []),
            "grid_hidden": list(grid_hidden or []),
            "part_method": part_method or "",
            "apply_mask": bool(apply_mask),
            "correction": dict(correction or {}),
            "load_columns": list(load_columns or []),
            "renames": dict(renames or {}),
        }
        _path(cache_dir).write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        pass  # persistence is best-effort; never block on it


def _save_merged(cache_dir: Path, **overrides) -> None:
    """Save the full state with only ``overrides`` changed (the rest preserved).

    The single-field setters below route through this so none of them can drop
    a sibling field — used at build time so a choice is saved even before any
    derived column, filter or grid change triggers a full ``save_state``.
    """
    st = load_state(cache_dir)
    st.update(overrides)
    save_state(
        cache_dir,
        grid_header=st["grid_header"],
        derivations=st["derivations"],
        removed=st["removed"],
        filters=st["filters"],
        grid_columns=st["grid_columns"],
        grid_order=st["grid_order"],
        grid_hidden=st["grid_hidden"],
        part_method=st["part_method"],
        apply_mask=st["apply_mask"],
        correction=st["correction"],
        load_columns=st["load_columns"],
        renames=st["renames"],
    )


def set_part_method(cache_dir: Path, method: str) -> None:
    """Persist just the part-assignment method, preserving the rest."""
    _save_merged(cache_dir, part_method=method)


def set_apply_mask(cache_dir: Path, value: bool) -> None:
    """Persist just the Apply-mask flag, preserving the rest."""
    _save_merged(cache_dir, apply_mask=bool(value))


def set_renames(cache_dir: Path, renames: dict) -> None:
    """Persist just the column renames, preserving the rest."""
    _save_merged(cache_dir, renames=dict(renames or {}))


def set_load_columns(cache_dir: Path, columns: list | None) -> None:
    """Persist just the build's column selection, preserving the rest."""
    _save_merged(cache_dir, load_columns=list(columns or []))


def set_correction(cache_dir: Path, correction: dict) -> None:
    """Persist just the correction recipe, preserving the rest."""
    _save_merged(cache_dir, correction=dict(correction or {}))
