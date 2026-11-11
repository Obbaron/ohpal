"""Macros: record a sequence of actions, save it to a file, run it again.

A macro is the list of actions (:mod:`actions` ops + params) committed between
Record and Stop. Three rules make a recording replayable on another build:

- **Columns are stored by their original datastore name.** The app stores
  formulas and filters under *display* names, which differ per build once a
  column is renamed — so every column name / ``[reference]`` in a step is
  translated display -> original when recorded (:func:`canonical`) and
  original -> the target build's display name when run (:func:`resolve`).
  Columns the macro itself creates are not source columns, so they pass
  through by name.
- **Build-specific data is never stored.** A parts-CSV / laser-parameter step
  records only *which* columns to import and re-reads the target build's CSV.
  An Excel-import step records the sheet + column headers and asks for the
  file when run; its key/value table is dropped from the file.
- **View-only actions are not recorded** (show/hide), nor are undo/redo
  themselves: an undo while recording simply drops the step it undid.
- **Outputs are steps too** — creating a plot, exporting to Excel. They change
  nothing that undo tracks, so an undo never removes them from a recording. A
  plot is stored as created (type, columns, layer span, options); an export
  stores what to write but not where — it asks for the file when run.

The file is plain, versioned JSON so it can be read and hand-edited.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QObject, QSettings, pyqtSignal

FORMAT = "ampm-macro"
VERSION = 1
FILE_FILTER = "AMPM macro (*.macro.json);;JSON (*.json)"
SUFFIX = ".macro.json"

_BRACKET = re.compile(r"\[([^\[\]]*)\]")

# Which params of each recordable op hold column names. ``names`` are single
# column names, ``lists`` lists of names, ``refs`` DSL strings with [column]
# references, ``rules`` a label's rule list (each rule's "cond" is a DSL
# string), ``nested`` a dict param whose listed keys are column names, ``pairs``
# a list of [column, something] pairs. ``drop`` params never reach the file.
# Ops absent from this table are not recordable.
_SCHEMA: dict[str, dict] = {
    "derive": {"names": ("name", "group", "after"), "refs": ("expr",)},
    "label": {"names": ("name",), "rules": ("rules",)},
    "excel_import": {"names": ("name", "key"), "drop": ("mapping",)},
    "part_calc": {"names": ("signal", "name")},
    "laser_params": {},
    "parts_csv_import": {},
    "rename": {"names": ("old",)},  # "new" is the literal new name
    "remove": {"lists": ("names",)},
    "restore": {"names": ("name",)},
    "filter_add": {"refs": ("condition",)},
    "filter_edit": {"refs": ("condition",)},
    "filter_remove": {},
    "filter_remove_last": {},
    "filter_reset": {},
    # outputs (not undoable)
    "plot": {"nested": {"spec": ("x", "y", "z", "color", "group_by")}},
    "export_excel": {"names": ("key",), "lists": ("columns",),
                     "pairs": ("values",), "drop": ("path",)},
}
OPS = frozenset(_SCHEMA)


# -- recently used macro files (app-wide, newest first) -----------------
_RECENT_KEY = "macros/recent"
_RECENT_MAX = 8


def _settings() -> QSettings:
    return QSettings("AMPM", "AMPM Analyzer")  # the store recents/geometry use


def recent() -> list[str]:
    """Recently saved / run macro files that still exist, newest first."""
    try:
        paths = json.loads(_settings().value(_RECENT_KEY, "[]") or "[]")
    except (ValueError, TypeError):
        return []
    return [p for p in paths if isinstance(p, str) and Path(p).is_file()]


def remember(path) -> None:
    """Put a macro file at the top of the recent list."""
    path = str(Path(path))
    paths = [path] + [p for p in recent() if p != path]
    _settings().setValue(_RECENT_KEY, json.dumps(paths[:_RECENT_MAX]))


class MacroError(ValueError):
    """A macro file that can't be read or isn't a valid macro."""


# -- column-name translation ------------------------------------------
def _map_refs(text, mapping: dict) -> str:
    """Rewrite every ``[column]`` token through ``mapping`` in ONE pass (so a
    swap such as A->B, B->A can't chain). Multi-column groups are handled per
    comma-separated token."""
    if not text or not mapping:
        return text

    def sub(m: re.Match) -> str:
        parts = [p.strip() for p in m.group(1).split(",")]
        return "[" + ", ".join(mapping.get(p, p) for p in parts) + "]"

    return _BRACKET.sub(sub, text)


def _translate(op: str, params: dict, mapping: dict) -> dict:
    spec = _SCHEMA[op]
    out = dict(params)
    for key in spec.get("names", ()):
        if isinstance(out.get(key), str):
            out[key] = mapping.get(out[key], out[key])
    for key in spec.get("lists", ()):
        if key in out:
            out[key] = [mapping.get(n, n) for n in out[key]]
    for key in spec.get("refs", ()):
        if isinstance(out.get(key), str):
            out[key] = _map_refs(out[key], mapping)
    for key in spec.get("rules", ()):
        if key in out:
            out[key] = [
                {**r, "cond": _map_refs(r.get("cond", ""), mapping)}
                for r in out[key]
            ]
    for key, fields in spec.get("nested", {}).items():
        if isinstance(out.get(key), dict):
            out[key] = {
                k: (mapping.get(v, v) if k in fields and isinstance(v, str) else v)
                for k, v in out[key].items()
            }
    for key in spec.get("pairs", ()):
        if out.get(key):
            out[key] = [[mapping.get(a, a), b] for a, b in out[key]]
    return out


def canonical(op: str, params: dict, renames: dict) -> dict:
    """Step params for the file: display names -> original datastore names.
    ``renames`` is the original -> display map in force when the action ran."""
    inverse = {disp: orig for orig, disp in (renames or {}).items()}
    out = _translate(op, params, inverse)
    for key in _SCHEMA[op].get("drop", ()):  # build-specific data stays out
        out.pop(key, None)
    return out


def resolve(op: str, params: dict, renames: dict) -> dict:
    """Step params for running: original names -> this build's display names."""
    return _translate(op, params, dict(renames or {}))


# -- plain-language step descriptions ---------------------------------
def describe(op: str, p: dict) -> str:
    if op == "derive":
        verb = "Overwrite" if p.get("overwrite") else "Add"
        return f"{verb} column '{p.get('name')}' = {p.get('expr')}"
    if op == "label":
        return (f"Add label column '{p.get('name')}' "
                f"({len(p.get('rules') or [])} rule(s))")
    if op == "excel_import":
        return (f"Import column '{p.get('name')}' from Excel, matched on "
                f"'{p.get('key')}' (asks for the file)")
    if op == "part_calc":
        return (f"Per-part {p.get('reducer')} of '{p.get('signal')}' "
                f"→ '{p.get('name')}'")
    if op == "laser_params":
        return "Add laser parameters from the parts CSV"
    if op == "parts_csv_import":
        items = p.get("items") or []
        shown = ", ".join(f"{s} / {c}" for s, c in items[:3])
        more = f" (+{len(items) - 3} more)" if len(items) > 3 else ""
        return f"Import {len(items)} parts-CSV column(s): {shown}{more}"
    if op == "rename":
        return f"Rename '{p.get('old')}' to '{p.get('new')}'"
    if op == "remove":
        return f"Remove column(s): {', '.join(p.get('names') or [])}"
    if op == "restore":
        return f"Restore column '{p.get('name')}'"
    if op == "filter_add":
        return f"Add filter: {p.get('condition')}"
    if op == "filter_edit":
        return f"Change filter {int(p.get('index', 0)) + 1} to: {p.get('condition')}"
    if op == "filter_remove":
        return f"Remove filter {int(p.get('index', 0)) + 1}"
    if op == "filter_remove_last":
        return "Remove the last filter"
    if op == "filter_reset":
        return "Reset all filters"
    if op == "plot":
        s = p.get("spec") or {}
        kind = s.get("kind", "plot")
        if kind == "Histogram":
            what = f"of '{s.get('x')}'"
        elif kind == "Contour":
            what = f"of '{s.get('z')}' over '{s.get('x')}' × '{s.get('y')}'"
        elif s.get("z"):
            what = f"of '{s.get('x')}' × '{s.get('y')}' × '{s.get('z')}'"
        else:
            what = f"of '{s.get('y')}' against '{s.get('x')}'"
        if s.get("color"):
            what += f", coloured by '{s.get('color')}'"
        return f"Plot: {kind} {what} ({_span_text(p.get('span'))})"
    if op == "export_excel":
        if p.get("mode") == "summary":
            vals = ", ".join(f"{a} of '{c}'" for c, a in (p.get("values") or [])[:3])
            what = f"summary by '{p.get('key')}': {vals}"
        else:
            what = f"{len(p.get('columns') or [])} column(s) of rows"
        return (f"Export to Excel — {what} ({_span_text(p.get('scope'))}; "
                "asks where to save)")
    return op


def _span_text(span) -> str:
    mode, lo, hi = (list(span or []) + [None, None, None])[:3]
    if mode == "all":
        return "all layers"
    if mode == "current":
        return "the layer on screen"
    if mode == "range":
        return f"layers {lo}–{hi}"
    return f"layer {lo}"


# -- file I/O -----------------------------------------------------------
def save(path, name: str, steps: list[dict]) -> Path:
    """Write a macro file; returns the path actually written (suffix added)."""
    path = Path(path)
    if path.suffix.lower() != ".json":
        path = path.with_name(path.name + SUFFIX)
    doc = {
        "format": FORMAT,
        "version": VERSION,
        "name": name,
        "created": datetime.now().isoformat(timespec="seconds"),
        "steps": steps,
    }
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def macro_name(path) -> str:
    name = Path(path).name
    for suffix in (SUFFIX, ".json"):
        if name.lower().endswith(suffix):
            return name[: -len(suffix)]
    return name


def load(path) -> tuple[str, list[dict]]:
    """Read + validate a macro file -> ``(name, steps)``. Raises MacroError.

    Only the known, recordable ops are accepted, so a file can never reach
    anything but the actions a user could have performed by hand."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise MacroError(f"Couldn't read the file: {exc}") from exc
    except ValueError as exc:
        raise MacroError(f"The file isn't valid JSON: {exc}") from exc
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise MacroError("This file isn't an AMPM macro.")
    if doc.get("version") != VERSION:
        raise MacroError(
            f"This macro is version {doc.get('version')!r}; this app reads "
            f"version {VERSION}.")
    steps = doc.get("steps")
    if not isinstance(steps, list) or not steps:
        raise MacroError("The macro has no steps.")
    out = []
    for i, step in enumerate(steps, 1):
        if not isinstance(step, dict) or not isinstance(step.get("params", {}), dict):
            raise MacroError(f"Step {i} is malformed.")
        op = step.get("op")
        if op not in OPS:
            raise MacroError(f"Step {i} uses an unknown action {op!r}.")
        out.append({"op": op, "params": dict(step.get("params") or {})})
    return str(doc.get("name") or macro_name(path)), out


# -- recording ----------------------------------------------------------
class Recorder(QObject):
    """Captures the actions committed between ``start()`` and ``stop()``.

    It mirrors the undo stack for the span of the recording: every committed
    action pushes a mark (its step, or None for a non-recordable action such as
    show/hide); an undo takes the newest undoable mark out, a redo puts it back
    where it was. So an undone action leaves the macro, and undo/redo never
    appear as steps. Outputs (plots, exports) are marks undo skips over."""

    changed = pyqtSignal()  # recording started / stopped / step count changed

    def __init__(self, actions, parent=None) -> None:
        super().__init__(parent)
        self.active = False
        # live actions since start, in order: (step or None, undoable?)
        self._marks: list[tuple[dict | None, bool]] = []
        # marks taken off by undo: (position they were at, step)
        self._undone: list[tuple[int, dict | None]] = []
        self._pre_undone = 0                    # undos reaching before start
        actions.performed.connect(self._on_performed)
        actions.noted.connect(self._on_noted)
        actions.undone.connect(self._on_undone)
        actions.redone.connect(self._on_redone)

    def start(self) -> None:
        self.active = True
        self._marks, self._undone, self._pre_undone = [], [], 0
        self.changed.emit()

    def stop(self) -> list[dict]:
        """End the recording and return its steps."""
        steps = self.steps()
        self.cancel()
        return steps

    def cancel(self) -> None:
        if self.active:
            self.active = False
            self._marks, self._undone, self._pre_undone = [], [], 0
            self.changed.emit()

    def steps(self) -> list[dict]:
        return [step for step, _undoable in self._marks if step is not None]

    def count(self) -> int:
        return len(self.steps())

    def _on_performed(self, op: str, params: dict, renames_before: dict) -> None:
        if not self.active:
            return
        step = None
        if op in OPS:
            step = {"op": op, "params": canonical(op, params, renames_before)}
        self._marks.append((step, True))
        self._undone, self._pre_undone = [], 0  # a new action clears redo
        self.changed.emit()

    def _on_noted(self, op: str, params: dict, renames: dict) -> None:
        """An output (plot / export) was made: a step undo never removes."""
        if not self.active or op not in OPS:
            return
        self._marks.append(
            ({"op": op, "params": canonical(op, params, renames)}, False))
        self.changed.emit()

    def _on_undone(self) -> None:
        if not self.active:
            return
        last = next((i for i in range(len(self._marks) - 1, -1, -1)
                     if self._marks[i][1]), None)
        if last is not None:
            self._undone.append((last, self._marks.pop(last)[0]))
        else:
            self._pre_undone += 1  # undid something from before Record
        self.changed.emit()

    def _on_redone(self) -> None:
        if not self.active:
            return
        if self._pre_undone:
            self._pre_undone -= 1
        elif self._undone:
            at, step = self._undone.pop()
            self._marks.insert(min(at, len(self._marks)), (step, True))
        self.changed.emit()
