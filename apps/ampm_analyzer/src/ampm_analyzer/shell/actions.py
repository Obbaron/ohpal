"""The action layer: one entry point for every user action that changes the
data's shape or view.

The window gathers parameters (usually from a dialog) and calls
``actions.run(op, **params)``. Each op is a single *intent-level* action with
plain, serialisable parameters — a multi-step gesture such as per-part CoV or a
parts-CSV import is ONE action — so it is one undo step now and one macro step
later.

``run`` snapshots the state, applies the action, and — if anything changed —
pushes an undo entry, persists, and emits ``performed`` (the hook a macro
recorder listens to). A failed action that half-applied is rolled back, so every
action is all-or-nothing.

Undoable state (the snapshot): derived columns, removed columns, renames,
filters and the hidden-column set. Column order is carried only to put a
re-appearing column back where it was; layer navigation, selection, column
widths and plots are not part of the history.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

from PyQt6.QtCore import QObject, pyqtSignal

from . import colref
from .history import History

# Snapshot keys that define "did anything change" / "does the frame's shape
# change" (order is positional help only, never a change in itself).
_STATE_KEYS = ("derivations", "removed", "renames", "filters", "hidden")
_SHAPE_KEYS = ("derivations", "removed", "renames")


@dataclass
class Outcome:
    ok: bool
    message: str = ""   # status-bar text ("" = say nothing)
    label: str = ""     # undo label ("Add column 'X'")


def _names_preview(names, limit: int = 6) -> str:
    """"a, b, c" — capped with "(+N more)" so a status line stays short."""
    names = list(names)
    if len(names) <= limit:
        return ", ".join(names)
    return ", ".join(names[:limit]) + f" (+{len(names) - limit} more)"


def _rename_pairs(before: list[str], after: list[str]) -> list[tuple[str, str]]:
    """Columns that were purely renamed between two column lists (same length,
    differing only by name in place) as ``(old, new)`` pairs; else []."""
    if len(before) != len(after):
        return []
    pairs = [(b, a) for b, a in zip(before, after) if b != a]
    olds, news = {b for b, _ in pairs}, {a for _, a in pairs}
    if olds & set(after) or news & set(before):
        return []  # names moved around rather than being renamed
    return pairs


class Actions(QObject):
    performed = pyqtSignal(str, dict)  # (op, params) of each committed action

    def __init__(self, host, controller, session, parent=None) -> None:
        super().__init__(parent)
        self._host = host          # the main window (grid, plots, persistence)
        self._c = controller
        self._s = session
        self.history = History(parent=self)

    # -- snapshot ------------------------------------------------------
    def capture(self) -> dict:
        dt = self._host._data_tab
        return {
            "derivations": copy.deepcopy(self._s.derivations),
            "removed": list(self._s.removed),
            "renames": dict(self._s.renames),
            "filters": list(self._c.filters()),
            "hidden": sorted(dt.hidden_columns()) if dt is not None else [],
            "order": list(dt.layout_names()[1]) if dt is not None else [],
        }

    @staticmethod
    def _differs(a: dict, b: dict, keys=_STATE_KEYS) -> bool:
        return any(a[k] != b[k] for k in keys)

    def restore(self, snap: dict) -> None:
        """Put the app back into a captured state: shaping model, filters, the
        grid (renamed in place, hidden set, re-appearing columns back in their
        old position) and the live plots."""
        host, dt = self._host, self._host._data_tab
        current = self.capture()
        shape_changed = self._differs(current, snap, _SHAPE_KEYS)
        cols_before = self._c.current_columns()

        self._s.derivations = copy.deepcopy(snap["derivations"])
        self._s.removed = list(snap["removed"])
        self._s.renames = dict(snap["renames"])
        self._c.set_filters(snap["filters"])  # the refresh below applies them

        # A pure rename: relabel the grid layout and live plot specs in place,
        # exactly as the forward rename does, so nothing moves.
        pairs = _rename_pairs(cols_before, self._c.current_columns())
        for old, new in pairs:
            if dt is not None:
                dt.rename_in_layout(old, new)
            for tab in host._plot_tabs:
                if getattr(tab, "context", None) is None:
                    tab.spec = colref.rename_spec(tab.spec, old, new)
        if dt is not None:
            dt.set_renames(self._s.renames)

        host._quiet_refresh = True  # re-shape in place; don't jump to the Data tab
        try:
            self._c.refresh_grid()
        finally:
            host._quiet_refresh = False

        if dt is not None:
            renamed = {new for _, new in pairs}
            came_back = [c for c in dt._columns
                         if c not in cols_before and c not in renamed]
            dt.blockSignals(True)  # one save at the end, not one per column
            try:
                dt.apply_hidden(set(snap["hidden"]))
                self._replace_columns(dt, came_back, snap["order"])
            finally:
                dt.blockSignals(False)
        if shape_changed:
            host._reshape_plots()
        host._after_restore()

    @staticmethod
    def _replace_columns(dt, names: list[str], order: list[str]) -> None:
        """Put columns that just re-appeared back where ``order`` had them (each
        after its nearest surviving predecessor)."""
        present = set(dt._columns)
        wanted = set(names)
        for i, name in enumerate(order):
            if name not in wanted:
                continue
            pred = next((p for p in reversed(order[:i]) if p in present), None)
            if pred is not None:
                dt.place_after(name, pred)

    # -- running an action ---------------------------------------------
    def run(self, op: str, **params) -> Outcome:
        handler = getattr(self, f"_do_{op}", None)
        if handler is None:
            return Outcome(False, f"Unknown action {op!r}.")
        before = self.capture()
        try:
            out = handler(**params)
        except Exception as exc:  # noqa: BLE001 — surface, and leave no half-state
            out = Outcome(False, f"Action failed: {exc}")
        after = self.capture()
        changed = self._differs(before, after)
        if not out.ok:
            if changed:
                self.restore(before)  # all-or-nothing
            return out
        if changed:
            if self._differs(before, after, _SHAPE_KEYS):
                self._host._reshape_plots()
            self.history.push(out.label or op, before, after)
            self._host._save_ui()
            self.performed.emit(op, dict(params))
        return out

    def undo(self) -> str | None:
        entry = self.history.take_undo()
        if entry is None:
            return None
        self.restore(entry.before)
        return entry.label

    def redo(self) -> str | None:
        entry = self.history.take_redo()
        if entry is None:
            return None
        self.restore(entry.after)
        return entry.label

    def reset(self) -> None:
        """Drop the history (a build was loaded or rebuilt)."""
        self.history.clear()

    # -- helpers -------------------------------------------------------
    def _taken(self) -> set[str]:
        """Every column name currently in use (grid columns + derived)."""
        return set(self._c.current_columns()) | {
            d["name"] for d in self._s.derivations}

    # -- column actions ------------------------------------------------
    def _do_derive(self, name, expr, group="", overwrite=False, after="") -> Outcome:
        err = self._c.add_derivation(name, expr, group, overwrite=overwrite)
        if err:
            return Outcome(False, f"Derive column failed: {err}")
        dt = self._host._data_tab
        if not overwrite and after and dt is not None:
            dt.place_after(name, after)  # position the new column in the grid
        verb = "Overwrote" if overwrite else "Added derived"
        return Outcome(True, f"{verb} column '{name}'.",
                       f"{'Overwrite' if overwrite else 'Add'} column '{name}'")

    def _do_label(self, name, rules, default="") -> Outcome:
        err = self._c.add_label_derivation(name, rules, default)
        if err:
            return Outcome(False, f"Group label failed: {err}")
        return Outcome(True, f"Added label column '{name}' ({len(rules)} rule(s)).",
                       f"Add label column '{name}'")

    def _do_excel_import(self, name, key, mapping, dtype="f64") -> Outcome:
        err = self._c.add_join_derivation(name, key, mapping, dtype)
        if err:
            return Outcome(False, f"Add from Excel failed: {err}")
        return Outcome(
            True,
            f"Added column '{name}' from Excel ({len(mapping)} keys on '{key}').",
            f"Add column '{name}' from Excel")

    def _do_part_calc(self, signal, reducer, name) -> Outcome:
        """Per-part reduction of a signal. CoV lays out three columns — per-part
        mean, per-part std, then their ratio — reusing the mean/std if present."""
        pid = self._c.part_id_display()  # rename-aware part column
        if reducer != "cov":
            err = self._c.add_derivation(name, f"{reducer}([{signal}]) by [{pid}]")
            if err:
                return Outcome(False, f"Per-part calculation failed: {err}")
            return Outcome(True, f"Added per-part column '{name}'.",
                           f"Add per-part column '{name}'")
        existing = self._taken()
        mean_name = f"{signal} (mean/part)"
        std_name = f"{signal} (std/part)"
        if name in existing:
            return Outcome(False, f"A column named {name!r} already exists.")
        plan = []
        if mean_name not in existing:
            plan.append((mean_name, f"mean([{signal}]) by [{pid}]"))
        if std_name not in existing:
            plan.append((std_name, f"std([{signal}]) by [{pid}]"))
        for nm, expr in plan:
            err = self._c.add_derivation(nm, expr)
            if err:
                return Outcome(False, f"Per-part CoV failed on '{nm}': {err}")
        err = self._c.add_derivation(name, f"[{std_name}] / [{mean_name}]")
        if err:
            return Outcome(False, f"Per-part CoV failed: {err}")
        return Outcome(
            True,
            f"Added per-part CoV '{name}' (+ {mean_name!r}, {std_name!r}).",
            f"Add per-part CoV '{name}'")

    def _do_laser_params(self) -> Outcome:
        """Join the QuantAM per-part scan-volume laser parameters onto the grid,
        keyed on the (rename-aware) part_id — one join per numeric column;
        existing names are skipped."""
        import polars as pl

        from . import derive

        pid = self._c.part_id_display()
        try:
            params = self._c.part_laser_parameters()
        except Exception as exc:  # noqa: BLE001 — surfaced, non-fatal
            return Outcome(False, f"Couldn't load laser parameters: {exc}")
        if params is None or "part_id" not in params.columns:
            return Outcome(False, "The parts CSV has no part_id column.")
        keys = params["part_id"].cast(pl.Utf8).to_list()
        taken = self._taken()
        added, skipped = [], []
        for col in (c for c in params.columns if c != "part_id"):
            series = params[col]
            if col in taken or not series.dtype.is_numeric():
                skipped.append(col)  # present already / only numerics join as f64
                continue
            mapping = {
                derive.norm_key(k): float(v)
                for k, v in zip(keys, series.to_list())
                if k is not None and v is not None
            }
            if not mapping:
                continue
            if self._c.add_join_derivation(col, pid, mapping, "f64") is None:
                added.append(col)
                taken.add(col)
            else:
                skipped.append(col)
        if not added:
            return Outcome(True, "No new laser-parameter columns to add"
                           + (" (all already present)." if skipped else "."))
        return Outcome(
            True,
            f"Added {len(added)} laser-parameter column(s): {_names_preview(added)}.",
            "Add laser parameters")

    def _do_parts_csv_import(self, items) -> Outcome:
        """Join each staged ``(section, column)`` of the parts CSV onto the grid,
        keyed on the (rename-aware) part_id. A name that clashes (e.g. 'Hatches
        Power' in two sections) is suffixed with its section."""
        import polars as pl

        from . import derive

        try:
            sect = dict(self._c.parts_csv_sections())
        except Exception as exc:  # noqa: BLE001 — surfaced, non-fatal
            return Outcome(False, f"Couldn't read the parts CSV: {exc}")
        pid = self._c.part_id_display()
        taken = self._taken()
        added, skipped = [], []
        for section, col in items:
            body = sect.get(section)
            if body is None or col not in body.columns:
                continue
            name = col if col not in taken else f"{col} ({section})"
            if name in taken:
                skipped.append(col)
                continue
            keys = body["part_id"].cast(pl.Utf8).to_list()
            series = body[col]
            numeric = series.dtype.is_numeric()
            mapping = {
                derive.norm_key(k): (float(v) if numeric else str(v))
                for k, v in zip(keys, series.to_list())
                if k is not None and v is not None
            }
            if not mapping:
                continue
            dtype = "f64" if numeric else "str"
            if self._c.add_join_derivation(name, pid, mapping, dtype) is None:
                added.append(name)
                taken.add(name)
            else:
                skipped.append(col)
        if not added:
            return Outcome(True, "No new columns imported from the parts CSV.")
        return Outcome(
            True,
            f"Imported {len(added)} column(s) from the parts CSV: "
            f"{_names_preview(added)}.",
            "Import parts CSV columns")

    def _do_rename(self, old, new) -> Outcome:
        """Rename a column across the whole app: controller state (renames map /
        derivation names / references), the grid layout and live plots."""
        old, new = (old or "").strip(), (new or "").strip()
        err = self._c.rename_error(old, new)
        if err:
            return Outcome(False, f"Rename failed: {err}")
        host, dt = self._host, self._host._data_tab
        # Pre-swap the grid's name layout so the controller's refresh keeps the
        # column exactly where it is (only the label changes).
        if dt is not None:
            dt.rename_in_layout(old, new)
        self._c.rename_column(old, new)  # validated above; mutates + refreshes
        # Live (session-linked) plots follow the rename; frozen detached plots
        # keep their own names.
        for tab in host._plot_tabs:
            if getattr(tab, "context", None) is None:
                tab.spec = colref.rename_spec(tab.spec, old, new)
        if dt is not None:
            dt.set_renames(self._s.renames)  # keep defaults current
        return Outcome(True, f"Renamed '{old}' to '{new}'.",
                       f"Rename '{old}' to '{new}'")

    def _do_remove(self, names) -> Outcome:
        names = list(names)
        blocked = self._c.remove_columns(names)
        done = [n for n in names if n not in blocked]
        parts = []
        if done:
            parts.append(f"Removed {len(done)} column(s): {', '.join(done)}.")
        if blocked:
            parts.append(f"Can't remove required column(s): {', '.join(blocked)}.")
        label = (f"Remove column '{done[0]}'" if len(done) == 1
                 else f"Remove {len(done)} columns")
        return Outcome(bool(done), " ".join(parts), label)

    def _do_restore(self, name) -> Outcome:
        self._c.restore_column(name)
        return Outcome(True, f"Restored column '{name}'.",
                       f"Restore column '{name}'")

    def _do_set_visible(self, name, visible) -> Outcome:
        dt = self._host._data_tab
        if dt is None:
            return Outcome(False)
        dt.set_column_visible(name, bool(visible))
        return Outcome(True, "", f"{'Show' if visible else 'Hide'} column '{name}'")

    # -- filter actions ------------------------------------------------
    def _do_filter_add(self, condition) -> Outcome:
        self._c.add_filter(condition)
        return Outcome(True, "", "Add filter")

    def _do_filter_edit(self, index, condition) -> Outcome:
        self._c.edit_filter(index, condition)
        return Outcome(True, "", "Edit filter")

    def _do_filter_remove(self, index) -> Outcome:
        self._c.remove_filter(index)
        return Outcome(True, "", "Remove filter")

    def _do_filter_remove_last(self) -> Outcome:
        self._c.remove_last_filter()
        return Outcome(True, "", "Remove filter")

    def _do_filter_reset(self) -> Outcome:
        self._c.reset_filters()
        return Outcome(True, "", "Reset filters")
