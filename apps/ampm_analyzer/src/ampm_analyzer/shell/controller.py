"""Application controller — the bridge between widgets and ohpal.

Owns the ``BuildSession`` and all threading. Widget signals call controller
methods; the controller talks to ohpal (heavy work off-thread) and writes the
session, which emits change signals the window reacts to. The controller never
touches widgets except to raise file dialogs / prompts (main-thread, modal).

Stage 2 adds the New / Open flows and the parquet-cache build:
- New  → prepare a fresh build (create config if missing) → DataStore setup.
- Open → open a prepared build; load-and-show if a cache exists, else prompt.
"""

from __future__ import annotations

import re
from pathlib import Path

from PyQt6.QtCore import QObject, QThread
from PyQt6.QtWidgets import QFileDialog, QMessageBox, QWidget

from . import derive
from .datastore_settings import REQUIRED_COLUMNS
from .recents import RecentStore
from .state import BuildSession, QueryResult
from .workers import CacheWorker, QueryWorker

# Same packet-filename shape the DataStore expects.
_PACKET_RE = re.compile(r"^Packet data for layer \d+, laser \d+\.txt$", re.IGNORECASE)

# Cap the rows handed to the (non-virtualised) grid; virtualised model = Stage 3.
STAGE1_ROW_CAP = 5000


def _has_packets(path: Path) -> bool:
    try:
        return any(_PACKET_RE.match(p.name) for p in path.iterdir() if p.is_file())
    except OSError:
        return False


class AppController(QObject):
    def __init__(self, window: QWidget, session: BuildSession) -> None:
        super().__init__(window)
        self._window = window
        self.session = session
        self._thread: QThread | None = None
        self._worker = None
        self._busy = False
        self._config: dict = {}
        self._setup_force = False  # True when the pending build should overwrite
        self._columns: list[str] | None = None  # selected load columns (None = all)
        self._filter: list[str] = []  # active row-filter conditions (grid-live)
        self._base_df = None  # last raw grid query output, before shaping
        # All queries (grid + per-plot spans) serialize through one worker to
        # avoid concurrent cache builds racing. Each item: dict(span, dest, label,
        # coalesce). Grid requests coalesce (latest wins); plot requests don't.
        self._queue: list[dict] = []
        self._current: dict | None = None
        self._recents = RecentStore()

    # -- entry points --------------------------------------------------
    def new_build(self) -> None:
        self._start("new")

    def open_build(self) -> None:
        self._start("open")

    def open_recent(self, path: str) -> None:
        """Open a build chosen from the Recent list (treated like Open)."""
        if self._busy:
            return
        self._load(Path(path), "open")

    def _start(self, mode: str) -> None:
        if self._busy:
            return
        title = "Prepare a new build" if mode == "new" else "Open a prepared build"
        chosen = QFileDialog.getExistingDirectory(
            self._window, title, self._recents.start_dir()
        )
        if not chosen:
            return
        # Remember where they were browsing (the picked folder's parent) so the
        # dialog can fall back to it next time even with no recents.
        self._recents.set_last_browse_dir(str(Path(chosen).parent))
        self._load(Path(chosen), mode)

    # -- load/prepare --------------------------------------------------
    def _load(self, build_root: Path, mode: str) -> None:
        self._busy = True
        self.session.begin_load(build_root.name)
        try:
            if mode == "new":
                config = self._ensure_and_load_config(build_root)
            else:  # open
                if not (build_root / "config.toml").exists():
                    # Not a prepared build — offer to set one up.
                    if not self._confirm(
                        "No DataStore found for this build.\n\n"
                        "Would you like to create one?"
                    ):
                        self._finish_idle("Open cancelled — no DataStore.")
                        return
                    config = self._ensure_and_load_config(build_root)
                else:
                    config = self._guarded(lambda: self._load_config(build_root))
            source_dir = Path(config["SOURCE"])
            thickness = float(config.get("LAYER_THICKNESS") or 0.03) or 0.03
            store = self._construct_store(source_dir, thickness)
        except Exception as exc:  # noqa: BLE001
            self._finish_idle(None)
            self.session.fail(str(exc))
            return

        self._config = config
        self._columns = None  # default to all; the setup page's build may narrow it
        self._filter = []     # a fresh build starts unfiltered
        # Record this build in the recents list (before set_store so the
        # backstage refresh triggered by the load already sees it).
        cached_now, _ = self._cache_status(store)
        self._recents.record(build_root, has_cache=cached_now > 0)
        self.session.set_store(store, source_dir, build_root.name, thickness)
        # Apply the configured assignment so builds opened straight from cache
        # (no setup page) still surface part_id; a later build overrides it.
        self._apply_part_assignment(store, config.get("METHOD"))

        cached, _total = self._cache_status(store)
        exists = cached > 0

        if mode == "open":
            if exists:
                self._begin_query(store)
            else:
                if self._confirm(
                    "No DataStore found for this build.\n\n"
                    "Would you like to create one?"
                ):
                    self._setup_force = False
                    self._finish_idle(None)
                    self.session.require_setup(config, store.layers, store.columns, False)
                else:
                    self._finish_idle("Open cancelled — no DataStore.")
            return

        # mode == "new"
        if exists:
            if self._confirm(
                "Existing DataStore found for this build.\n\n"
                "Would you like to overwrite it?"
            ):
                self._setup_force = True
                self._finish_idle(None)
                self.session.require_setup(config, store.layers, store.columns, True)
            else:
                self._begin_query(store)  # keep the existing cache, just open it
        else:
            self._setup_force = False
            self._finish_idle(None)
            self.session.require_setup(config, store.layers, store.columns, False)

    # -- build the cache (from the setup page) -------------------------
    def build_datastore(
        self,
        scope: tuple[int, int] | None,
        thickness: float | None = None,
        recipe: dict | None = None,
    ) -> None:
        store = self.session.store
        if store is None or self._busy:
            return
        # Apply an edited layer thickness: reconstruct the store so the build
        # (and later queries, where Z = layer × thickness) use it.
        if (
            thickness
            and self.session.source_dir is not None
            and abs(thickness - self.session.layer_thickness) > 1e-9
        ):
            store = self._construct_store(self.session.source_dir, thickness)
            self.session.store = store
            self.session.layer_thickness = thickness
        # Part assignment (dhxml → part_id) per the chosen recipe, else config.
        method = (recipe or {}).get("part_method") or self._config.get("METHOD")
        self._apply_part_assignment(store, method)
        # Restrict later queries to the columns the user kept (None = all).
        self._columns = (recipe or {}).get("columns") or None
        if scope is None:
            layers = list(store.layers)
        else:
            lo, hi = scope
            layers = [L for L in store.layers if lo <= L <= hi]
        if not layers:
            self.session.fail("No layers in the selected range.")
            return
        self._busy = True
        self.session.begin_load("DataStore")
        self._start_cache(store, layers, self._setup_force)

    # -- config helpers ------------------------------------------------
    def _ensure_and_load_config(self, build_root: Path) -> dict:
        def work() -> dict:
            if not (build_root / "config.toml").exists():
                from ohpal.ampm.setup_build import create_config

                create_config(build_root)
            return self._load_config(build_root)

        return self._guarded(work)

    @staticmethod
    def _load_config(build_root: Path) -> dict:
        from ohpal.ampm.config import load_config

        return load_config(build_root)

    @staticmethod
    def _guarded(fn):
        """Run fn, turning ohpal's sys.exit() into a RuntimeError."""
        try:
            return fn()
        except SystemExit as exc:
            raise RuntimeError(str(exc)) from exc

    @staticmethod
    def _construct_store(source_dir: Path, layer_thickness: float):
        from ohpal.ampm import DataStore

        return DataStore(source_dir, layer_thickness=layer_thickness)

    def _apply_part_assignment(self, store, method: str) -> None:
        """Configure the store's part assignment for the chosen method.

        Only ``dhxml`` is wired (bounding-box containment from the build's
        .dhxml); every other method clears assignment. Failing to load the
        dhxml is surfaced but non-fatal — the build proceeds without part_id.
        """
        if (method or "").lower() == "dhxml":
            dhxml = (self._config or {}).get("DHXML")
            if dhxml:
                try:
                    from ohpal.ampm.parts import BuildStartedDHXML

                    table = BuildStartedDHXML.from_dhxml(dhxml).parts_table()
                    store.set_part_assignment(table)
                    return
                except Exception as exc:  # noqa: BLE001
                    self.session.fail(f"Could not load DHXML parts: {exc}")
        store.set_part_assignment(None)

    @staticmethod
    def _cache_status(store) -> tuple[int, int]:
        cached = sum(1 for L in store.layers if store._cache_path(L).exists())
        return cached, len(store.layers)

    def current_config(self) -> dict:
        return self._config

    def cache_exists(self, store=None) -> bool:
        store = store or self.session.store
        if store is None:
            return False
        return self._cache_status(store)[0] > 0

    # -- prompts / state -----------------------------------------------
    def _confirm(self, text: str) -> bool:
        return (
            QMessageBox.question(
                self._window,
                "DataStore",
                text,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        )

    def _finish_idle(self, status: str | None) -> None:
        self._busy = False
        if status is not None:
            self.session.fail(status)

    # -- grid navigation (single layer) --------------------------------
    def show_layer(self, layer: int) -> None:
        """Show one layer in the grid (snapped; grid-only, coalesced)."""
        store = self.session.store
        if store is None:
            return
        L = min(store.layers, key=lambda x: abs(x - layer))
        if L == self.session.current_layer and self.session.result is not None:
            return
        self._request((L, L), self._deliver_grid, f"layer {L}", coalesce=True)

    def _resolve_span(self, mode: str, lo=None, hi=None) -> tuple[int, int]:
        layers = self.session.store.layers

        def snap(v):
            return min(layers, key=lambda x: abs(x - v))

        if mode == "all":
            return layers[0], layers[-1]
        lo = snap(lo if lo is not None else layers[0])
        hi = snap(hi if hi is not None else layers[-1])
        return (lo, hi) if lo <= hi else (hi, lo)

    # -- per-plot span query (its own dataset, not the grid's) ---------
    def query_for(self, mode: str, lo, hi, on_raw) -> None:
        """Query a plot's span off-thread; call ``on_raw(raw_df)`` when ready.

        Shaping (derived/removed columns) is applied by the caller via ``shape``
        so a plot can re-shape without re-querying.
        """
        store = self.session.store
        if store is None:
            return
        qlo, qhi = self._resolve_span(mode, lo, hi)
        label = f"plot layer {qlo}" if qlo == qhi else f"plot layers {qlo}–{qhi}"
        # quiet: no global loading UI — the plot tab shows its own overlay.
        self._request(
            (qlo, qhi), lambda res: on_raw(res.df), label, coalesce=False, quiet=True
        )

    # -- query queue (serialized worker) -------------------------------
    def _request(self, span, dest, label: str, coalesce: bool,
                 quiet: bool = False) -> None:
        if coalesce:  # drop any still-queued grid request; keep the latest
            self._queue = [r for r in self._queue if not r["coalesce"]]
        self._queue.append({
            "span": span, "dest": dest, "label": label,
            "coalesce": coalesce, "quiet": quiet,
        })
        if not self._busy:
            self._start_next()

    def _start_next(self) -> None:
        if self._busy or not self._queue:
            return
        req = self._queue.pop(0)
        self._current = req
        self._busy = True
        if not req["quiet"]:
            self.session.begin_load(req["label"])
        self._start_query(self.session.store, req["span"])

    def _begin_query(self, store) -> None:
        first = store.layers[0]
        self._busy = False  # release the load guard; the query queue takes over
        self._request((first, first), self._deliver_grid, f"layer {first}",
                      coalesce=True)

    def _query_columns(self, store) -> list[str] | None:
        """Columns to request: the user's kept set, plus part_id when the
        store has an active assignment (it's virtual, not in the kept set)."""
        if self._columns is None:
            return None
        cols = list(self._columns)
        if "part_id" in store.columns and "part_id" not in cols:
            cols.append("part_id")
        return cols

    def _start_query(self, store, layers: tuple[int, int]) -> None:
        thread = QThread(self)
        worker = QueryWorker(
            store, layers, columns=self._query_columns(store), row_cap=None
        )  # virtualised grid: no cap
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_query_finished)
        worker.error.connect(self._on_worker_error)
        self._wire_teardown(thread, worker)
        self._thread, self._worker = thread, worker
        thread.start()

    def _start_cache(self, store, layers: list[int], force: bool) -> None:
        thread = QThread(self)
        worker = CacheWorker(store, layers, force=force)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.session.cache_progress)
        worker.finished.connect(lambda _n: self._on_cache_finished(store))
        worker.error.connect(self._on_worker_error)
        self._wire_teardown(thread, worker)
        self._thread, self._worker = thread, worker
        thread.start()

    def _wire_teardown(self, thread: QThread, worker) -> None:
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        # Only clear if this is still the current thread — a query chained off a
        # cache build starts a new thread before the old one finishes tearing
        # down, and we must not null the new references.
        thread.finished.connect(lambda t=thread: self._clear_thread(t))

    def _on_query_finished(self, result) -> None:
        self._busy = False
        req = self._current
        self._current = None
        if req is not None:
            req["dest"](result)  # grid → _deliver_grid; plot → its callback
        self._start_next()  # run the next queued request, if any

    def _deliver_grid(self, result) -> None:
        self.session.current_layer = result.layers[0]
        self._base_df = result.df  # keep the raw output for re-shaping
        self._publish_grid(result.layers)

    def _publish_grid(self, layers) -> None:
        """Shape + filter the current base frame and push it to the grid."""
        if self._base_df is None:
            return
        shaped = self._shape(self._base_df)
        display = derive.filter_rows(shaped, self._filter)
        self.session.set_result(
            QueryResult(display, shaped.height, display.height, layers)
        )

    def refresh_grid(self) -> None:
        """Re-shape + re-filter the current grid in place (no re-query)."""
        if self._base_df is None:
            return
        L = self.session.current_layer
        self._publish_grid((L, L))

    # -- row filter (grid-live; plots snapshot it at creation) ---------
    def filters(self) -> list[str]:
        return list(self._filter)

    def set_filters(self, conditions, *, refresh: bool = False) -> None:
        """Replace the whole filter list (used to restore persisted filters)."""
        self._filter = [c for c in (conditions or []) if (c or "").strip()]
        if refresh:
            self.refresh_grid()

    def add_filter(self, condition: str) -> None:
        text = (condition or "").strip()
        if text:
            self._filter.append(text)
            self.refresh_grid()

    def edit_filter(self, index: int, condition: str) -> None:
        text = (condition or "").strip()
        if 0 <= index < len(self._filter) and text:
            self._filter[index] = text
            self.refresh_grid()

    def remove_filter(self, index: int) -> None:
        if 0 <= index < len(self._filter):
            self._filter.pop(index)
            self.refresh_grid()

    def remove_last_filter(self) -> None:
        if self._filter:
            self._filter.pop()
            self.refresh_grid()

    def reset_filters(self) -> None:
        if self._filter:
            self._filter = []
            self.refresh_grid()

    # -- column shaping (derive, then drop removed) --------------------
    def shape(self, df):
        """Apply the derived + removed-column pipeline to any frame. Public so a
        plot can re-shape its own span without re-querying."""
        return self._shape(df)

    def shape_filtered(self, df, conditions):
        """Shape, then apply a plot's snapshotted row filter (after derivation)."""
        return derive.filter_rows(self._shape(df), conditions or [])

    def _shape(self, df):
        if self.session.derivations:
            df = derive.apply(df, self.session.derivations)
        drop = [c for c in self.session.removed if c in df.columns]
        return df.drop(drop) if drop else df

    def add_derivation(
        self, name: str, expr_text: str, group: str = ""
    ) -> str | None:
        """Register a derived column and refresh the grid.

        ``group`` (optional) is a column to aggregate within. Returns an error
        message, or None on success.
        """
        base = self._base_df
        names = list(base.columns) if base is not None else []
        names += [d["name"] for d in self.session.derivations]
        if name in names:
            return f"A column named {name!r} already exists."
        try:
            derive.compile_expr(expr_text, names)
        except derive.DeriveError as exc:
            return str(exc)
        self.session.derivations.append(
            {"kind": "formula", "name": name, "expr": expr_text, "group": group}
        )
        self._refresh_derived()
        return None

    def add_label_derivation(
        self, name: str, rules: list[dict], default: str = ""
    ) -> str | None:
        """Register a label column from if/elif/else rules. Returns error/None."""
        base = self._base_df
        names = list(base.columns) if base is not None else []
        names += [d["name"] for d in self.session.derivations]
        if name in names:
            return f"A column named {name!r} already exists."
        if not rules:
            return "Add at least one rule."
        for rule in rules:
            try:
                derive.compile_predicate(rule["cond"], names)
            except derive.DeriveError as exc:
                return str(exc)
        self.session.derivations.append(
            {"kind": "label", "name": name, "rules": rules, "default": default}
        )
        self._refresh_derived()
        return None

    def remove_derivation(self, name: str) -> None:
        self.session.derivations = [
            d for d in self.session.derivations if d["name"] != name
        ]
        self._refresh_derived()

    # -- remove / restore columns --------------------------------------
    def remove_columns(self, names: list[str]) -> list[str]:
        """Remove columns from the view. A derived/label column has its
        derivation deleted; a source column is projected out of every result.
        Required columns can't be removed. Returns the names that were blocked.
        """
        deriv_names = {d["name"] for d in self.session.derivations}
        base_cols = set(self._base_df.columns) if self._base_df is not None else set()
        blocked, changed = [], False
        for n in names:
            if n in deriv_names:
                self.session.derivations = [
                    d for d in self.session.derivations if d["name"] != n
                ]
                changed = True
            elif n in REQUIRED_COLUMNS:
                blocked.append(n)
            elif n in base_cols and n not in self.session.removed:
                self.session.removed.append(n)
                changed = True
        if changed:
            self._refresh_derived()
        return blocked

    def restore_column(self, name: str) -> None:
        if name in self.session.removed:
            self.session.removed.remove(name)
            self._refresh_derived()

    def _refresh_derived(self) -> None:
        if self._base_df is None or self.session.result is None:
            return
        self._publish_grid(self.session.result.layers)

    def _on_cache_finished(self, store) -> None:
        # Cache built — now show the first layer in the grid.
        first = store.layers[0]
        self._busy = False
        self._request((first, first), self._deliver_grid, f"layer {first}",
                      coalesce=True)

    def _on_worker_error(self, message: str) -> None:
        self._busy = False
        self._current = None
        self.session.fail(message)
        self._start_next()  # don't strand the queue on one failure

    def _clear_thread(self, thread: QThread) -> None:
        if self._thread is thread:
            self._thread = None
            self._worker = None

    # -- shutdown ------------------------------------------------------
    def shutdown(self) -> None:
        if self._worker is not None and hasattr(self._worker, "cancel"):
            self._worker.cancel()
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(3000)
