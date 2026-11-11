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

from . import colref, derive
from .datastore_settings import REQUIRED_COLUMNS
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
    note: str = ""      # worth repeating after a macro run (partial part match)


class _Sim:
    """The column state a macro pre-check walks through, step by step, WITHOUT
    touching the app: source columns (by original name, shown through the
    rename map), derived columns, removed columns and the filter count.

    Each check reports its issues and then applies the step's intended effect
    here even if it had an issue — so one broken step doesn't make every later
    step that builds on it look broken too."""

    def __init__(self, controller, session) -> None:
        self.base = controller.source_column_names()      # original names
        self.renames = dict(session.renames)              # original -> display
        self.derived = [d["name"] for d in session.derivations]
        self.removed = list(session.removed)
        self.n_filters = len(controller.filters())
        self.pre_existing = set(self.derivable())         # before the macro

    def display(self, orig: str) -> str:
        return self.renames.get(orig, orig)

    def orig(self, display: str) -> str | None:
        return next((o for o in self.base if self.display(o) == display), None)

    def base_display(self) -> list[str]:
        return [self.display(o) for o in self.base]

    def derivable(self) -> list[str]:
        """Names a formula may reference / collide with (incl. removed)."""
        return self.base_display() + self.derived

    def current(self) -> list[str]:
        """Names in the grid (removed columns excluded)."""
        return [c for c in self.derivable() if c not in self.removed]

    def taken(self) -> set[str]:
        return set(self.current()) | set(self.derived)

    def add(self, name: str) -> None:
        if name not in self.derived:
            self.derived.append(name)


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
    # (op, params, renames in force before it ran) of each committed action —
    # the macro recorder listens to these three.
    performed = pyqtSignal(str, dict, dict)
    undone = pyqtSignal()
    redone = pyqtSignal()
    # (op, params, renames) of an OUTPUT the user just made — a plot, an export.
    # It changes nothing undo tracks, so it isn't an undo step, but a macro
    # records it.
    noted = pyqtSignal(str, dict, dict)

    def __init__(self, host, controller, session, parent=None) -> None:
        super().__init__(parent)
        self._host = host          # the main window (grid, plots, persistence)
        self._c = controller
        self._s = session
        self.history = History(parent=self)
        self._batch_plots: list = []  # plots opened by the macro now running

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
            self.performed.emit(op, dict(params), dict(before["renames"]))
        return out

    def run_batch(self, label: str, steps, prepare=None):
        """Run a list of ``(op, params)`` as ONE all-or-nothing action (a macro
        run): one undo step on success; on the first failing step everything is
        rolled back. ``prepare(op, params)`` is called just before each step
        (the macro runner uses it to resolve column names against the state the
        earlier steps left). Returns ``(failed, message, notes)``: ``failed`` is
        None on success, else the index of the step that failed; ``notes`` are
        the steps' remarks worth showing afterwards (e.g. a partial part
        match)."""
        before = self.capture()
        notes: list[str] = []
        self._batch_plots = []
        host = self._host
        quiet, host._quiet_refresh = host._quiet_refresh, True  # stay on the tab
        try:
            for i, (op, params) in enumerate(steps):
                handler = getattr(self, f"_do_{op}", None)
                try:
                    if handler is None:
                        out = Outcome(False, f"Unknown action {op!r}.")
                    else:
                        out = handler(
                            **(prepare(op, params) if prepare else params))
                except Exception as exc:  # noqa: BLE001 — surface, roll back
                    out = Outcome(False, f"Action failed: {exc}")
                if not out.ok:
                    for tab in self._batch_plots:  # plots this run opened
                        host._close_plot(tab)
                    if self._differs(before, self.capture()):
                        self.restore(before)
                    return i, out.message or "The step could not be applied.", []
                if out.note:
                    notes.append(out.note)
        finally:
            host._quiet_refresh = quiet
            self._batch_plots = []
        after = self.capture()
        if self._differs(before, after):
            if self._differs(before, after, _SHAPE_KEYS):
                self._host._reshape_plots()
            self.history.push(label, before, after)
            self._host._save_ui()
        return None, "", notes

    # -- macro pre-check -------------------------------------------------
    def check_batch(self, steps, resolve) -> list[tuple[int, str]]:
        """Check a whole macro against this build WITHOUT changing anything.

        Walks the steps over a simulated column state (:class:`_Sim`) and
        returns every problem as ``(step_index, message)`` — an empty list means
        the macro can run. ``resolve(op, params, renames)`` turns a step's
        stored column names into the display names in force at that step.

        The checks mirror what each ``_do_*`` handler (and the controller behind
        it) enforces, and are deliberately a little stricter where a handler
        would quietly skip or rename: on a different build that silence would
        hide a wrong result. ``run_batch`` still rolls back if a step fails
        anyway, so a gap here can't leave a half-applied macro."""
        sim = _Sim(self._c, self._s)
        ctx: dict = {}  # per-run cache (parts CSV reads)
        issues: list[tuple[int, str]] = []
        for i, (op, params) in enumerate(steps):
            checker = getattr(self, f"_check_{op}", None)
            if checker is None:
                issues.append((i, f"Unknown action {op!r}."))
                continue
            try:
                found = checker(sim, ctx, **resolve(op, params, sim.renames))
            except TypeError as exc:  # a hand-edited step with wrong settings
                found = [f"The step's settings aren't valid: {exc}"]
            except Exception as exc:  # noqa: BLE001 — report, never crash
                found = [f"Couldn't check this step: {exc}"]
            issues.extend((i, msg) for msg in found)
        return issues

    @staticmethod
    def _compiles(fn, text, names) -> list[str]:
        try:
            fn(text, names)
            return []
        except derive.DeriveError as exc:
            return [str(exc)]

    @staticmethod
    def _exists(name) -> str:
        return f"A column named {name!r} already exists."

    def _parts_ready(self, need_csv: bool) -> list[str]:
        out = []
        if not self._c.has_part_assignment():
            out.append("This build has no part assignment, so there is no "
                       "part column to work with.")
        if need_csv and not self._c.has_laser_parameters():
            out.append("This build has no parts CSV.")
        return out

    def _match(self, keys) -> tuple[int, int] | None:
        """(matched, total) parts of the build covered by ``keys`` (normalised
        join keys), or None when the build's part ids aren't known."""
        ids = self._c.assigned_part_ids()
        if not ids:
            return None
        return len(ids & set(keys)), len(ids)

    def _check_derive(self, sim, ctx, name, expr, group="", overwrite=False,
                      after="") -> list[str]:
        names = sim.derivable()
        out = [self._exists(name)] if name in names and not overwrite else []
        out += self._compiles(derive.compile_expr, expr, names)
        sim.add(name)
        return out

    def _check_label(self, sim, ctx, name, rules, default="") -> list[str]:
        names = sim.derivable()
        out = [self._exists(name)] if name in names else []
        if not rules:
            out.append("Add at least one rule.")
        for rule in rules or []:
            out += self._compiles(derive.compile_predicate, rule.get("cond", ""), names)
        sim.add(name)
        return list(dict.fromkeys(out))

    def _check_excel_import(self, sim, ctx, name, key, mapping=None, dtype="f64",
                            source=None) -> list[str]:
        names = sim.derivable()
        out = [self._exists(name)] if name in names else []
        if key not in names:
            out.append(f"Key column {key!r} isn't in this build.")
        src = source or {}
        if mapping is None and not (src.get("sheet") and src.get("key_column")
                                    and src.get("value_column")):
            out.append("The step doesn't say which sheet and columns to read.")
        sim.add(name)
        return out

    def _check_part_calc(self, sim, ctx, signal, reducer, name) -> list[str]:
        out = self._parts_ready(need_csv=False)
        names = sim.derivable()
        pid = sim.display("part_id")
        if out:  # no part column: only the signal is still worth checking
            if signal not in names:
                out.append(f"Unknown column: {signal!r}")
        else:
            fn = "mean" if reducer == "cov" else reducer
            out += self._compiles(
                derive.compile_expr, f"{fn}([{signal}]) by [{pid}]", names)
        if reducer == "cov":
            if name in sim.taken():
                out.append(self._exists(name))
            sim.add(f"{signal} (mean/part)")  # reused if already there
            sim.add(f"{signal} (std/part)")
        elif name in names:
            out.append(self._exists(name))
        sim.add(name)
        return out

    def _check_laser_params(self, sim, ctx) -> list[str]:
        out = self._parts_ready(need_csv=True)
        if out:
            return out
        try:
            params = self._c.part_laser_parameters()
        except Exception as exc:  # noqa: BLE001
            return [f"Couldn't load laser parameters: {exc}"]
        if params is None or "part_id" not in params.columns:
            return ["The parts CSV has no part_id column."]
        taken = sim.taken()
        for col in (c for c in params.columns if c != "part_id"):
            if not params[col].dtype.is_numeric():
                continue
            if col in taken:
                if col in sim.pre_existing:  # made earlier in this macro: skipped
                    out.append(self._exists(col))
                continue
            sim.add(col)
        keys = {derive.norm_key(k) for k in params["part_id"].to_list()
                if k is not None}
        got = self._match(keys)
        if got is not None and got[0] == 0:
            out.append(f"None of the build's {got[1]} parts match the parts CSV "
                       "— the imported columns would be empty.")
        return out

    def _check_parts_csv_import(self, sim, ctx, items) -> list[str]:
        out = self._parts_ready(need_csv=True)
        if out:
            return out
        if "sections" not in ctx:
            try:
                ctx["sections"] = dict(self._c.parts_csv_sections())
            except Exception as exc:  # noqa: BLE001
                return [f"Couldn't read the parts CSV: {exc}"]
        sect = ctx["sections"]
        taken = sim.taken()
        unmatched = set()
        for section, col in items:
            body = sect.get(section)
            if body is None:
                out.append(f"The parts CSV has no section {section!r}.")
                continue
            if col not in body.columns:
                out.append(f"Section {section!r} has no column {col!r}.")
                continue
            # The handler would rename a clashing import to "col (section)".
            # Against a column this build already had, that silent rename would
            # leave later steps reading the wrong column — so it is an issue.
            name = col if col not in taken else f"{col} ({section})"
            if (col in taken and col in sim.pre_existing) or name in taken:
                out.append(self._exists(col))
                continue
            sim.add(name)
            taken.add(name)
            keys = {derive.norm_key(k) for k in body["part_id"].to_list()
                    if k is not None}
            got = self._match(keys)
            if got is not None and got[0] == 0 and section not in unmatched:
                unmatched.add(section)
                out.append(
                    f"None of the build's {got[1]} parts match section "
                    f"{section!r} — the imported columns would be empty.")
        return out

    def _check_rename(self, sim, ctx, old, new) -> list[str]:
        old, new = (old or "").strip(), (new or "").strip()
        current = sim.current()
        if not new:
            return ["Give the column a name."]
        out = []
        if new == old:
            out.append("That's already the column's name.")
        elif old not in current:
            out.append(f"Column {old!r} isn't in the grid.")
        elif new in current or new in sim.removed:
            out.append(self._exists(new))
        orig = sim.orig(old)
        if orig is not None:
            sim.renames[orig] = new
        elif old in sim.derived:
            sim.derived[sim.derived.index(old)] = new
        return out

    def _check_remove(self, sim, ctx, names) -> list[str]:
        out = []
        for n in names:
            orig = sim.orig(n)
            if n in sim.derived:
                sim.derived.remove(n)
            elif orig is not None and orig in REQUIRED_COLUMNS:
                out.append(f"Can't remove required column {n!r}.")
            elif orig is not None and n not in sim.removed:
                sim.removed.append(n)
            else:
                out.append(f"Column {n!r} isn't in the grid.")
        return out

    def _check_restore(self, sim, ctx, name) -> list[str]:
        if name not in sim.removed:
            return [f"{name!r} isn't a removed column."]
        sim.removed.remove(name)
        return []

    def _check_filter_add(self, sim, ctx, condition) -> list[str]:
        sim.n_filters += 1
        if not (condition or "").strip():
            return ["The filter is empty."]
        return self._compiles(derive.compile_predicate, condition, sim.current())

    def _check_filter_edit(self, sim, ctx, index, condition) -> list[str]:
        out = []
        if not 0 <= int(index) < sim.n_filters:
            out.append(f"There is no filter {int(index) + 1} to change.")
        if not (condition or "").strip():
            out.append("The filter is empty.")
        else:
            out += self._compiles(
                derive.compile_predicate, condition, sim.current())
        return out

    def _check_filter_remove(self, sim, ctx, index) -> list[str]:
        if not 0 <= int(index) < sim.n_filters:
            return [f"There is no filter {int(index) + 1} to remove."]
        sim.n_filters -= 1
        return []

    def _check_filter_remove_last(self, sim, ctx) -> list[str]:
        if sim.n_filters <= 0:
            return ["There is no filter to remove."]
        sim.n_filters -= 1
        return []

    def _check_filter_reset(self, sim, ctx) -> list[str]:
        sim.n_filters = 0
        return []

    # -- outputs: plots and Excel exports (macro steps, not undoable) ----
    def _shape_state(self) -> dict:
        """The shaping state right now — an export made mid-macro writes the
        data as it stood at that step, not as later steps leave it."""
        return {
            "derivations": copy.deepcopy(self._s.derivations),
            "removed": list(self._s.removed),
            "renames": dict(self._s.renames),
            "filters": list(self._c.filters()),
        }

    def _span_issues(self, span, *, single_ok: bool = False) -> list[str]:
        """Problems with a recorded layer span on THIS build. ``all`` and
        ``current`` adapt to any build; a fixed layer or range must exist."""
        store = self._s.store
        layers = list(store.layers) if store is not None else []
        mode, lo, hi = (list(span or []) + [None, None, None])[:3]
        if mode in ("all", "current") or not layers:
            return []
        if mode == "single":
            if single_ok or lo in (self._c.available_layers() or layers):
                return []
            return [f"Layer {lo} has no data on this build."]
        if mode == "range":
            if lo is None or hi is None or lo < layers[0] or hi > layers[-1]:
                return [f"Layers {lo}–{hi} are outside this build's layers "
                        f"({layers[0]}–{layers[-1]})."]
            return []
        return [f"Unknown layer span {mode!r}."]

    def _do_plot(self, spec, span) -> Outcome:
        from .plotspec import PlotSpec

        ps = PlotSpec(**spec)
        mode, lo, hi = (list(span) + [None, None, None])[:3]
        if ps.is_layer_viewer:  # its layer is only where the scrubber starts
            lo = hi = self._s.current_layer
        tab = self._host._open_plot(ps, (mode, lo, hi))
        self._batch_plots.append(tab)
        return Outcome(True)

    def _check_plot(self, sim, ctx, spec, span) -> list[str]:
        from .plotspec import PLOT_KINDS, PlotSpec

        try:
            ps = PlotSpec(**spec)
        except TypeError as exc:
            return [f"The plot's settings aren't valid: {exc}"]
        out = []
        if ps.kind not in PLOT_KINDS:
            out.append(f"Unknown plot type {ps.kind!r}.")
        cols = set(sim.current())
        used = [ps.x] + ([] if ps.is_hist else [ps.y]) + [ps.z, ps.color, ps.group_by]
        for name in dict.fromkeys(n for n in used if n):
            if name not in cols:
                out.append(f"Unknown column: {name!r}")
        out += self._span_issues(span, single_ok=ps.is_layer_viewer)
        return out

    def _do_export_excel(self, mode, scope, path, sheet="Export",
                         respect_filters=True, key=None, values=None,
                         columns=None, filename=None) -> Outcome:
        spec = {
            "mode": mode, "scope": tuple(scope), "path": path, "sheet": sheet,
            "respect_filters": bool(respect_filters), "key": key,
            "values": [tuple(v) for v in (values or [])],
            "columns": list(columns) if columns else None,
        }
        self._host._start_export(spec, self._shape_state())
        return Outcome(True)

    def _check_export_excel(self, sim, ctx, mode, scope, path=None, sheet="Export",
                            respect_filters=True, key=None, values=None,
                            columns=None, filename=None) -> list[str]:
        cols = set(sim.current())
        out = []
        if mode == "summary":
            wanted = [key] + [c for c, _agg in (values or [])]
            if not values:
                out.append("The export has no value columns.")
        elif mode == "raw":
            wanted = list(columns or [])
        else:
            return [f"Unknown export type {mode!r}."]
        for name in dict.fromkeys(wanted):
            if name not in cols:
                out.append(f"Unknown column: {name!r}")
        out += self._span_issues(scope)
        return out

    def undo(self) -> str | None:
        entry = self.history.take_undo()
        if entry is None:
            return None
        self.restore(entry.before)
        self.undone.emit()
        return entry.label

    def redo(self) -> str | None:
        entry = self.history.take_redo()
        if entry is None:
            return None
        self.restore(entry.after)
        self.redone.emit()
        return entry.label

    def reset(self) -> None:
        """Drop the history (a build was loaded or rebuilt)."""
        self.history.clear()

    def note(self, op: str, **params) -> None:
        """Report an output the user just made (plot, export) so a macro being
        recorded can capture it. Not an undo step."""
        self.noted.emit(op, dict(params), dict(self._s.renames))

    # -- helpers -------------------------------------------------------
    def _match_text(self, keys, what: str) -> tuple[str, str]:
        """How many of the build's parts an import's keys cover, as (a sentence
        to append to the status, a note if the match is only partial)."""
        got = self._match(keys)
        if got is None:
            return "", ""
        matched, total = got
        text = f" Matched {matched} of {total} parts."
        note = (f"{what}: matched {matched} of {total} parts."
                if matched < total else "")
        return text, note

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

    def _do_excel_import(self, name, key, mapping, dtype="f64", source=None) -> Outcome:
        # ``source`` (sheet + column headers) isn't needed to apply the join; it
        # rides along so a recorded macro can re-read another file the same way.
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
        matched, note = self._match_text(
            {derive.norm_key(k) for k in keys if k is not None}, "Laser parameters")
        return Outcome(
            True,
            f"Added {len(added)} laser-parameter column(s): "
            f"{_names_preview(added)}.{matched}",
            "Add laser parameters", note)

    def _do_parts_csv_import(self, items) -> Outcome:
        """Join each staged ``(section, column)`` of the parts CSV onto the grid,
        keyed on the (rename-aware) part_id. A name that clashes (e.g. 'Hatches
        Power' in two sections) is suffixed with its section."""
        import polars as pl

        try:
            sect = dict(self._c.parts_csv_sections())
        except Exception as exc:  # noqa: BLE001 — surfaced, non-fatal
            return Outcome(False, f"Couldn't read the parts CSV: {exc}")
        pid = self._c.part_id_display()
        taken = self._taken()
        added, skipped = [], []
        all_keys: set[str] = set()
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
                all_keys.update(mapping)
            else:
                skipped.append(col)
        if not added:
            return Outcome(True, "No new columns imported from the parts CSV.")
        matched, note = self._match_text(all_keys, "Parts CSV import")
        return Outcome(
            True,
            f"Imported {len(added)} column(s) from the parts CSV: "
            f"{_names_preview(added)}.{matched}",
            "Import parts CSV columns", note)

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
