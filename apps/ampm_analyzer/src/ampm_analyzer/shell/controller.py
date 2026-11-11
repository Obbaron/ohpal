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

import os
import re
from pathlib import Path

from PyQt6.QtCore import QObject, QThread
from PyQt6.QtWidgets import QFileDialog, QWidget

from . import colref, derive, uistate
from .message_dialog import ask as _ask, tell as _tell
from .datastore_settings import REQUIRED_COLUMNS
from .recents import RecentStore
from .state import BuildSession, QueryResult
from .workers import CacheWorker, QueryWorker

# Same packet-filename shape the DataStore expects.
_PACKET_RE = re.compile(r"^Packet data for layer \d+, laser \d+\.txt$", re.IGNORECASE)

# Cap the rows handed to the (non-virtualised) grid; virtualised model = Stage 3.
STAGE1_ROW_CAP = 5000

# Row budget for a plot query. A plot span can be the whole build (tens of
# millions of rows) but a scatter only draws ~150k points; the query is
# downsampled to this many rows to cap memory (derived group-stats like a
# per-part CoV are then computed on the sample — close, but approximate).
_PLOT_SAMPLE_ROWS = 1_000_000

# Correction (MeltVIEW melt-pool XY-bias): the raw input columns it needs loaded,
# and the source column an "override" writes back to. See ohpal.ampm.correction.
_CORR_SOURCE = "MeltVIEW melt pool (mean)"
_CORR_INPUTS = ("Demand X", "Demand Y", "LaserVIEW (mean)", _CORR_SOURCE)


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
        # Masking: drop points outside the STL layer polygons. The mask is built
        # off-thread (heavy, cached) on its own thread refs so it runs in parallel
        # with query/cache work, then applied as the first step of _shape.
        self._apply_mask = False       # Apply-mask toggle for this build
        self._mask_geom = None         # built Mask (dict[int, polygon]) or None
        self._mask_key = None          # (stl, layers, thickness) the mask is for
        self._mask_thread: QThread | None = None
        self._mask_worker = None
        # Correction recipe (on/machine/column/mode/output). Empty / on=False is
        # off. Applied inline in _shape (cheap numpy transform — no worker).
        self._correction: dict = {}
        # part_ids the active part assignment can put on the data (None = no
        # assignment) — lets an import report how many parts it matched.
        self._part_ids: set[str] | None = None
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
        """Begin loading a build. The expensive part — loading/creating the config
        and constructing the DataStore, where the ~2s cold ``import ohpal`` (->
        polars) happens — runs on a worker thread so the window never freezes. The
        rest resumes on the main thread in ``_on_load_done``."""
        self._busy = True
        # A build with no config.toml needs one created. For Open, confirm first
        # (on the main thread, before the worker starts).
        create = not (build_root / "config.toml").exists()
        if mode == "open" and create and not self._confirm(
            "No DataStore found for this build.\n\n"
            "Would you like to create one?",
            ok_text="Create",
        ):
            self._finish_idle("Open cancelled — no DataStore.")
            return
        self.session.begin_load(build_root.name)
        self._pump()  # paint "Loading <build>…" before the (threaded) heavy work
        self._start_load(build_root, mode, create)

    def _start_load(self, build_root: Path, mode: str, create: bool) -> None:
        from .workers import LoadWorker

        thread = QThread(self)
        worker = LoadWorker(build_root, create=create)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(
            lambda res: self._on_load_done(build_root, mode, res))
        worker.error.connect(self._on_load_error)
        self._wire_teardown(thread, worker)
        self._thread, self._worker = thread, worker
        thread.start()

    def _on_load_error(self, message: str) -> None:
        self._finish_idle(None)
        self.session.fail(message)

    def _on_load_done(self, build_root: Path, mode: str, result) -> None:
        """Main-thread continuation once the worker has the config + store: set up
        session state, then decide whether to query the cache or go to setup."""
        config, store, source_dir, thickness, _elapsed = result
        self._config = config
        self._columns = None  # all, unless this build saved a selection (below)
        self._filter = []     # a fresh build starts unfiltered
        # Overlay the part-assignment method the user chose at build time
        # (persisted per-build) — config.toml doesn't record it, so without this
        # a reopened cached build loses its part_id. Set before set_store so the
        # setup form it repopulates also shows the real choice.
        saved_state = uistate.load_state(store.cache_dir)
        saved_method = saved_state.get("part_method")
        if saved_method:
            self._config["METHOD"] = saved_method
        # Restore the Apply-mask choice (also not in config.toml).
        self._apply_mask = bool(saved_state.get("apply_mask"))
        self._correction = dict(saved_state.get("correction") or {})
        # Load the same source columns the build was made with, not all of them.
        kept = [c for c in saved_state.get("load_columns") or []
                if c in store.columns]
        self._columns = kept or None
        cached, _total = self._cache_status(store)
        # Record this build in the recents list (before set_store so the backstage
        # refresh triggered by the load already sees it).
        self._recents.record(build_root, has_cache=cached > 0)
        self.session.set_store(store, source_dir, build_root.name, thickness)
        # Apply the configured assignment so builds opened straight from cache
        # (no setup page) still surface part_id; a later build overrides it.
        self._apply_part_assignment(store, self._config.get("METHOD"))
        # Kick off the mask build now (parallel to the first query) if masking
        # was on for this build — the ready mask shapes the grid on arrival.
        self._ensure_mask()

        exists = cached > 0

        if mode == "open":
            if exists:
                self._begin_query(store)
            else:
                if self._confirm(
                    "No DataStore found for this build.\n\n"
                    "Would you like to create one?",
                    ok_text="Create",
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
                "Would you like to overwrite it?",
                ok_text="Overwrite",
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
        if (method or "").lower() == "dbscan":
            _tell(
                self._window, "Part assignment",
                "DBSCAN part assignment isn't implemented yet.\n\n"
                "Building without a part assignment.",
            )
        self._apply_part_assignment(store, method)
        # Persist the choice (config.toml doesn't record it) and keep the
        # in-memory config in step, so reopening this cached build re-applies it.
        self._config["METHOD"] = method
        uistate.set_part_method(store.cache_dir, method)
        # Masking toggle (persist like part_method) — build the mask off-thread
        # so it's ready to shape the grid once the cache query returns.
        self._apply_mask = bool((recipe or {}).get("apply_mask"))
        uistate.set_apply_mask(store.cache_dir, self._apply_mask)
        self._ensure_mask()
        # Correction recipe (persist like masking) — applied inline in _shape.
        corr = dict((recipe or {}).get("correction") or {})
        corr["on"] = bool((recipe or {}).get("apply_correction"))
        self._correction = corr
        uistate.set_correction(store.cache_dir, corr)
        # Column renames chosen on the setup form — authoritative for this build.
        # Applied as display names in _shape (after mask/correct, which use raw
        # names); persisted via the normal _save_ui path.
        self.session.renames = dict((recipe or {}).get("renames") or {})
        uistate.set_renames(store.cache_dir, self.session.renames)
        # Restrict later queries to the columns the user kept (None = all).
        self._columns = (recipe or {}).get("columns") or None
        uistate.set_load_columns(store.cache_dir, self._columns)
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

        ``dhxml`` → bounding-box containment from the build's .dhxml.
        ``direct`` → nearest part centre from the QuantAM parts CSV (capped by
        the config's MAX_DISTANCE_MM). Any other method (incl. ``dbscan``,
        not yet implemented) clears assignment. A load failure is surfaced but
        non-fatal — the build proceeds without part_id.
        """
        m = (method or "").lower()
        if m == "dhxml":
            dhxml = (self._config or {}).get("DHXML")
            if dhxml:
                try:
                    from ohpal.ampm.parts import BuildStartedDHXML

                    table = BuildStartedDHXML.from_dhxml(dhxml).parts_table()
                    store.set_part_assignment(table, method="bbox")
                    self._note_part_ids(table)
                    return
                except Exception as exc:  # noqa: BLE001
                    self.session.fail(f"Could not load DHXML parts: {exc}")
        elif m == "direct":
            parts_csv = (self._config or {}).get("PARTS_CSV")
            if parts_csv:
                try:
                    from ohpal.ampm.parts import QuantAMParts

                    table = QuantAMParts.from_path(parts_csv).parent_parts()
                    store.set_part_assignment(
                        table, method="nearest",
                        max_distance_mm=(self._config or {}).get("MAX_DISTANCE_MM"),
                    )
                    self._note_part_ids(table)
                    return
                except Exception as exc:  # noqa: BLE001
                    self.session.fail(f"Could not load parts CSV: {exc}")
        store.set_part_assignment(None)
        self._part_ids = None

    def _note_part_ids(self, table) -> None:
        try:
            self._part_ids = {
                derive.norm_key(v) for v in table["part_id"].to_list()
                if v is not None}
        except Exception:  # noqa: BLE001 — coverage reporting is best-effort
            self._part_ids = None

    def assigned_part_ids(self) -> set[str] | None:
        """Every part id the active assignment can put on the data (normalised
        like join keys), or None when unknown / no assignment."""
        return set(self._part_ids) if self._part_ids is not None else None

    def source_column_names(self) -> list[str]:
        """ORIGINAL names of the source columns in the loaded frame, plus the
        corrected column ``_shape`` injects — the base a macro pre-check
        simulates renames / removals on."""
        base = list(self._base_df.columns) if self._base_df is not None else []
        c = self._correction
        if c.get("on") and c.get("mode") != "override":
            out = (c.get("output") or "").strip() or f"{_CORR_SOURCE} corrected"
            if out not in base:
                base.append(out)
        return base

    @staticmethod
    def _cache_status(store) -> tuple[int, int]:
        """(cached_layers, total_layers). One directory read instead of a
        ``.exists()`` stat per layer — far cheaper as the layer count grows."""
        import os

        layers = store.layers
        try:
            present = {e.name for e in os.scandir(store.cache_dir)
                       if e.name.endswith(".parquet")}
        except OSError:
            present = set()
        cached = sum(1 for L in layers if store._cache_path(L).name in present)
        return cached, len(layers)

    @staticmethod
    def _pump() -> None:
        """Flush pending UI events so a just-set status / spinner actually paints
        before a blocking stretch of work on the main thread."""
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.processEvents()

    def current_config(self) -> dict:
        return self._config

    def cache_exists(self, store=None) -> bool:
        store = store or self.session.store
        if store is None:
            return False
        return self._cache_status(store)[0] > 0

    # -- prompts / state -----------------------------------------------
    def _confirm(self, text: str, *, ok_text: str = "Yes") -> bool:
        return _ask(self._window, "DataStore", text,
                    ok_text=ok_text, cancel_text="Cancel")

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
        pool = self.available_layers() or list(store.layers)
        L = min(pool, key=lambda x: abs(x - layer))
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
        so a plot can re-shape without re-querying. A plot's span can be the
        whole build (tens of millions of rows) but it only draws ~150k points,
        so the query is downsampled to a bounded budget to cap memory.
        """
        store = self.session.store
        if store is None:
            return
        qlo, qhi = self._resolve_span(mode, lo, hi)
        label = f"plot layer {qlo}" if qlo == qhi else f"plot layers {qlo}–{qhi}"
        # quiet: no global loading UI — the plot tab shows its own overlay.
        self._request(
            (qlo, qhi), lambda res: on_raw(res.df), label, coalesce=False,
            quiet=True, sample_to=_PLOT_SAMPLE_ROWS,
        )

    # -- query queue (serialized worker) -------------------------------
    def _request(self, span, dest, label: str, coalesce: bool,
                 quiet: bool = False, sample_to: int | None = None) -> None:
        if coalesce:  # drop any still-queued grid request; keep the latest
            self._queue = [r for r in self._queue if not r["coalesce"]]
        self._queue.append({
            "span": span, "dest": dest, "label": label,
            "coalesce": coalesce, "quiet": quiet, "sample_to": sample_to,
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
        self._start_query(self.session.store, req["span"], req.get("sample_to"))

    def _begin_query(self, store) -> None:
        first = self._landing_layer(store)
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

    def _start_query(self, store, layers: tuple[int, int],
                     sample_to: int | None = None) -> None:
        thread = QThread(self)
        worker = QueryWorker(
            store, layers, columns=self._query_columns(store),
            row_cap=None, sample_to=sample_to,
        )  # virtualised grid: no cap; plots pass a sample budget
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
        # The mask can arrive while this query was in flight and rule its layer
        # out (nothing of the part there). Don't show an empty layer the selector
        # can't even reach — go to the lowest layer that has data instead.
        avail = self.available_layers()
        if avail and result.layers[0] not in avail:
            target = self._landing_layer()
            self._request((target, target), self._deliver_grid,
                          f"layer {target}", coalesce=True)
            return
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

    def current_columns(self) -> list[str]:
        """Column names currently shown in the grid (after rename + derive, less
        removed) — the set a rename validates against."""
        if self._base_df is None:
            return [d["name"] for d in self.session.derivations]
        cols = [self.session.renames.get(c, c) for c in self._base_df.columns]
        extra = self._correction_new_column()
        if extra and extra not in cols:
            cols.append(extra)  # the corrected column _shape injects
        cols += [d["name"] for d in self.session.derivations]
        return [c for c in cols if c not in self.session.removed]

    def _derivable_columns(self) -> list[str]:
        """Names a new derivation / filter may reference and collide with:
        renamed source columns plus derived names. Unlike ``current_columns``
        this keeps *removed* columns, because the removed drop happens after
        derivations run, so a derivation may still reference them."""
        base = []
        if self._base_df is not None:
            base = [self.session.renames.get(c, c) for c in self._base_df.columns]
        extra = self._correction_new_column()
        if extra and extra not in base:
            base.append(extra)  # the corrected column _shape injects
        return base + [d["name"] for d in self.session.derivations]

    def _original_source_name(self, display: str) -> str:
        """The original datastore name whose current display is ``display``
        (or ``display`` itself if it was never renamed)."""
        for orig, cur in self.session.renames.items():
            if cur == display:
                return orig
        return display

    # -- part assignment ------------------------------------------------
    def part_id_display(self) -> str:
        """The current (possibly renamed) display name of the ``part_id``
        column — the name actions should reference."""
        return self.session.renames.get("part_id", "part_id")

    def has_part_assignment(self) -> bool:
        """True when the loaded build has a usable ``part_id`` — i.e. a
        successful part assignment, so the data carries real part values (not
        all null / ``"noise"``). The contextual Parts toolbar group keys off
        this. Checks the raw base frame, which still holds the original name."""
        import polars as pl

        df = self._base_df
        if df is None or "part_id" not in df.columns:
            return False
        try:
            real = df.select(
                pl.col("part_id").is_not_null() & (pl.col("part_id") != "noise")
            ).to_series()
            return bool(real.any())
        except Exception:  # noqa: BLE001 — never let a probe break the toolbar
            return False

    def has_laser_parameters(self) -> bool:
        """True when this build has a QuantAM parts CSV to pull per-part laser
        parameters from. (The dhxml carries only geometry, not parameters.)"""
        return bool((self._config or {}).get("PARTS_CSV"))

    def part_laser_parameters(self, *, variant: str = "1"):
        """Load the per-part scan-volume laser parameters as a Polars frame
        keyed by ``part_id`` (original name) from the QuantAM parts CSV.

        Returns the frame, or raises with a clear message. The caller joins the
        parameter columns onto the grid via ``add_join_derivation``."""
        path = (self._config or {}).get("PARTS_CSV")
        if not path:
            raise ValueError("This build has no parts CSV configured.")
        from ohpal.ampm.parts import QuantAMParts

        return QuantAMParts.from_path(path).volume_parameters_with_speed(
            variant=variant)

    def parts_csv_sections(self, *, variant: str = "1"):
        """Every section of the QuantAM parts CSV as ``(name, body_df)`` pairs,
        for the Import-parts-CSV picker.

        Each ``body_df`` is keyed by ``part_id`` with the section's own data
        columns; support rows (the ``.s`` variant of "Sr. No.") are dropped,
        leaving one row per placed part. The Parent Parts section has no variant
        suffix, so it passes through whole.

        ``part_id`` is the id part assignment puts on the grid, NOT the bare
        "Source Index": a name placed several times (a parametric build) is one
        row per copy, each ``Name#<instance>`` and carrying that copy's own
        values. Rows are matched to their instance by "Sr. No."
        (``"<instance>.<variant>"``); a row with no usable instance number falls
        back to its bare name."""
        import polars as pl

        from ohpal.ampm.parts import QuantAMParts, SECTION_PARENT

        path = (self._config or {}).get("PARTS_CSV")
        if not path:
            raise ValueError("This build has no parts CSV configured.")
        qp = QuantAMParts.from_path(path)
        try:  # instance number -> the grid's part id
            ids = qp.part_ids_by_instance().rename(
                {"Sr. No.": "_inst", "part_id": "_pid"})
        except Exception:  # noqa: BLE001 — no usable Parent Parts: bare names
            ids = None
        out = []
        for name in qp.section_names:
            df = qp[name]
            if "Source Index" not in df.columns:
                continue
            data_cols = [c for c in df.columns
                         if c not in ("Sr. No.", "Source Index")]
            if not data_cols:
                continue
            body = df
            if name != SECTION_PARENT and "Sr. No." in df.columns:
                sr = df["Sr. No."].cast(pl.Utf8)
                body = df.filter(sr.str.ends_with(f".{variant}"))
            bare = pl.col("Source Index").cast(pl.Utf8)
            if ids is not None and "Sr. No." in body.columns:
                body = (
                    body.with_columns(
                        pl.col("Sr. No.").cast(pl.Utf8).str.split(".")
                        .list.first().cast(pl.Int64, strict=False).alias("_inst"))
                    .join(ids, on="_inst", how="left", maintain_order="left")
                    .with_columns(pl.coalesce(pl.col("_pid"), bare).alias("part_id"))
                )
            else:
                body = body.with_columns(bare.alias("part_id"))
            out.append((name, body.select(["part_id", *data_cols])))
        return out

    def rename_error(self, old: str, new: str) -> str | None:
        """Validate a rename without mutating — lets the window pre-check before
        it touches the grid layout. Returns an error message, or None."""
        old, new = (old or "").strip(), (new or "").strip()
        if not new:
            return "Give the column a name."
        if new == old:
            return "That's already the column's name."
        current = self.current_columns()
        if old not in current:
            return f"Column {old!r} isn't in the grid."
        if new in current or new in self.session.removed:
            return f"A column named {new!r} already exists."
        return None

    def rename_column(self, old: str, new: str) -> str | None:
        """Rename a column everywhere: the renames map (source columns) or the
        derivation name (derived columns), plus every ``[old]`` reference in
        derivations and filters, and the removed list. Returns error / None.

        The caller (window) also rewrites open plot specs and the grid layout,
        then persists — this method owns only controller-side state.
        """
        old, new = (old or "").strip(), (new or "").strip()
        err = self.rename_error(old, new)
        if err:
            return err
        derived = {d["name"] for d in self.session.derivations}
        if old not in derived:
            # Source column: record the remap keyed by the original datastore
            # name, composing with any earlier rename of the same column.
            self.session.renames[self._original_source_name(old)] = new
        self.session.derivations = colref.rename_derivations(
            self.session.derivations, old, new)
        self._filter = colref.rename_filters(self._filter, old, new)
        self.session.removed = colref.rename_names(self.session.removed, old, new)
        self._refresh_derived()
        return None

    # -- masking (drop points outside the STL layer polygons) ----------
    _MASK_COLS = ("Demand X", "Demand Y", "layer")

    def apply_mask(self) -> bool:
        """Whether the Apply-mask toggle is active for this build (persisted)."""
        return self._apply_mask

    def available_layers(self) -> list[int]:
        """Layers the grid can actually show. Normally every cached layer; with
        masking on and the mask built, only the layers the part occupies — the
        rest are entirely masked away, so they'd show an empty grid. The layer
        selector is bound to this, so stepping/typing can't land on an empty
        layer. Falls back to all layers if the mask left nothing (never lock the
        user out)."""
        store = self.session.store
        if store is None:
            return []
        layers = list(store.layers)
        if self._apply_mask and self._mask_geom is not None:
            keep = {int(k) for k in self._mask_geom}
            masked = [L for L in layers if L in keep]
            if masked:
                return masked
        return layers

    def _landing_layer(self, store=None) -> int:
        """The layer the Data tab opens on: the lowest available layer that is
        already in the DataStore — never layer 1 by default, which may be masked
        away or not built. Falls back to the lowest available layer if none of
        them is cached yet."""
        store = store or self.session.store
        avail = self.available_layers() or list(store.layers)
        try:
            present = {e.name for e in os.scandir(store.cache_dir)
                       if e.name.endswith(".parquet")}
        except OSError:
            present = set()
        for layer in avail:
            if store._cache_path(layer).name in present:
                return layer
        return avail[0]

    def _mask(self, df):
        """Drop rows outside the STL layer mask, when masking is active and the
        mask is built. Uses the raw source columns, so this runs before rename.
        A no-op when the toggle is off, the mask isn't built yet, or the frame
        lacks the geometry columns (never let masking break the grid)."""
        if not self._apply_mask or self._mask_geom is None:
            return df
        if any(c not in df.columns for c in self._MASK_COLS):
            return df
        try:
            from ohpal.ampm.masking import apply_mask

            return apply_mask(df, self._mask_geom)
        except Exception:  # noqa: BLE001 - masking must never break shaping
            return df

    def _ensure_mask(self) -> None:
        """Start an off-thread mask build if masking is on and the held mask is
        missing or stale. A no-op when masking is off (clears the held mask), the
        build has no STL, or a matching mask is already built/building."""
        store = self.session.store
        if not self._apply_mask or store is None:
            self._mask_geom = None
            self._mask_key = None
            return
        stl = (self._config or {}).get("STL")
        if not stl:
            # Nothing to mask with — treat masking as off for this build.
            self._apply_mask = False
            self._mask_geom = None
            self._mask_key = None
            return
        layers = tuple(store.layers)
        thickness = self.session.layer_thickness
        key = (str(stl), layers, thickness)
        if self._mask_geom is not None and self._mask_key == key:
            return  # already built for these inputs
        if self._mask_thread is not None:
            return  # a build is already running
        cache_path = Path(store.cache_dir) / "mask.pkl"
        self._start_mask(stl, list(layers), thickness, cache_path, key)

    def _start_mask(self, stl, layers, thickness, cache_path, key) -> None:
        from .workers import MaskWorker

        thread = QThread(self)
        worker = MaskWorker(
            stl, layers, layer_thickness=thickness, cache_path=cache_path)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(lambda m, k=key: self._on_mask_done(m, k))
        worker.error.connect(self._on_mask_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_mask_thread)
        self._mask_thread, self._mask_worker = thread, worker
        self._window.set_status("Building mask…")
        thread.start()

    def _on_mask_done(self, mask, key) -> None:
        self._mask_geom = mask
        self._mask_key = key
        # Re-bind the layer selector to the masked layers, then make sure the
        # grid is on a layer that actually has data: if the current layer was
        # masked away entirely, re-query the first masked layer (which also
        # re-shapes it); otherwise re-shape the current one in place.
        try:
            self._window.refresh_data_layers()
        except Exception:  # noqa: BLE001
            pass
        avail = self.available_layers()
        cur = self.session.current_layer
        if avail and cur is not None and cur not in avail:
            self.show_layer(self._landing_layer())
        else:
            self.refresh_grid()
        try:
            self._window._reshape_plots()
        except Exception:  # noqa: BLE001
            pass
        n = len(mask) if mask else 0
        self._window.set_status(f"Mask applied across {n} layers.")

    def _on_mask_error(self, message: str) -> None:
        self._mask_geom = None
        self._mask_key = None
        self._window.set_status("Mask build failed — showing unmasked data.")

    def _clear_mask_thread(self) -> None:
        self._mask_thread = None
        self._mask_worker = None

    # -- correction (MeltVIEW melt-pool XY-bias) ------------------------
    def load_columns(self) -> list[str]:
        """The source columns this build loads (persisted); [] means all."""
        return list(self._columns or [])

    def correction(self) -> dict:
        """The correction recipe for this build (persisted). ``on``=False / {} is
        off; else keys machine/column/mode/output."""
        return dict(self._correction)

    def _correction_new_column(self) -> str | None:
        """Display name of the correction's *new* output column, when correction
        is on in new-column mode — so it can be listed as a first-class column
        (renameable / derivable). None for off or override mode."""
        c = self._correction
        if not c.get("on") or c.get("mode") == "override":
            return None
        out = (c.get("output") or "").strip() or f"{_CORR_SOURCE} corrected"
        return self.session.renames.get(out, out)

    def _correct(self, df):
        """Apply the MeltVIEW melt-pool XY-bias correction, adding a new column or
        overriding the source column. Uses the raw source columns, so this runs
        before rename. A no-op when correction is off or the required inputs
        aren't loaded (never let correction break shaping)."""
        c = self._correction
        if not c.get("on"):
            return df
        if any(col not in df.columns for col in _CORR_INPUTS):
            return df
        if c.get("mode") == "override":
            out = _CORR_SOURCE
        else:
            out = (c.get("output") or "").strip() or f"{_CORR_SOURCE} corrected"
        try:
            from ohpal.ampm.correction import MeltPoolCorrection

            return MeltPoolCorrection().apply(df, output_col=out)
        except Exception:  # noqa: BLE001 - correction must never break shaping
            return df

    def _shape(self, df):
        # Masking first: drop points outside the STL layer polygons, using the
        # raw source columns ("Demand X"/"Demand Y"/"layer") before any rename.
        df = self._mask(df)
        # Correction next (still on raw column names): add/override the corrected
        # melt-pool column before rename remaps anything.
        df = self._correct(df)
        # Renames next: a source column reads as its new name through the whole
        # pipeline (derivations, removed, filters, grid, plots).
        if self.session.renames:
            rmap = {o: n for o, n in self.session.renames.items()
                    if o in df.columns and n != o}
            if rmap:
                df = df.rename(rmap)
        if self.session.derivations:
            df = derive.apply(df, self.session.derivations)
        drop = [c for c in self.session.removed if c in df.columns]
        return df.drop(drop) if drop else df

    def add_derivation(
        self, name: str, expr_text: str, group: str = "", *, overwrite: bool = False
    ) -> str | None:
        """Register a derived column and refresh the grid.

        ``group`` (optional) is a column to aggregate within. ``overwrite`` lets
        the formula target an existing column: a source column is shadowed by a
        same-named formula (reversible by removing the derivation), and an
        existing derived column has its definition replaced in place. Returns an
        error message, or None on success.
        """
        derived_names = [d["name"] for d in self.session.derivations]
        names = self._derivable_columns()  # renamed source cols + derived names
        if name in names and not overwrite:
            return f"A column named {name!r} already exists."
        try:
            # Compile against all names; for overwrite the target is in scope, so
            # a self-referential formula (e.g. `[x] / 365` onto `x`) is allowed.
            derive.compile_expr(expr_text, names)
        except derive.DeriveError as exc:
            return str(exc)
        entry = {"kind": "formula", "name": name, "expr": expr_text, "group": group}
        if overwrite and name in derived_names:
            for i, d in enumerate(self.session.derivations):
                if d["name"] == name:
                    self.session.derivations[i] = entry  # replace definition
                    break
        else:
            self.session.derivations.append(entry)  # new, or shadow a source col
        self._refresh_derived()
        return None

    def add_label_derivation(
        self, name: str, rules: list[dict], default: str = ""
    ) -> str | None:
        """Register a label column from if/elif/else rules. Returns error/None."""
        names = self._derivable_columns()  # renamed source cols + derived names
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

    def add_join_derivation(
        self, name: str, key: str, mapping: dict, dtype: str = "f64"
    ) -> str | None:
        """Register an Excel-imported column: a key->value map left-joined onto
        the grid on ``key``. ``mapping`` is pre-normalised (canonical string
        keys). Returns an error message, or None on success."""
        names = self._derivable_columns()  # renamed source cols + derived names
        if name in names:
            return f"A column named {name!r} already exists."
        # The key may be a source column or an already-derived one (the join is
        # appended last, so earlier derivations are in scope at join time).
        if self._base_df is not None and key not in names:
            return f"Key column {key!r} isn't in this build."
        if not mapping:
            return "No key/value rows to import."
        self.session.derivations.append(
            {"kind": "join", "name": name, "key": key,
             "map": dict(mapping), "dtype": dtype}
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
        # Source columns by their current (possibly renamed) display name, since
        # names here come from the grid and removed entries are dropped after the
        # rename remap in _shape.
        base_cols = set()
        if self._base_df is not None:
            base_cols = {self.session.renames.get(c, c)
                         for c in self._base_df.columns}
        blocked, changed = [], False
        for n in names:
            if n in deriv_names:
                self.session.derivations = [
                    d for d in self.session.derivations if d["name"] != n
                ]
                changed = True
            elif self._original_source_name(n) in REQUIRED_COLUMNS:
                blocked.append(n)  # guard the original even if it was renamed
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
        # Cache built — show the first layer that carries data. With a cached
        # mask already in hand this is the first masked layer; otherwise the
        # first layer, and _on_mask_done re-lands once the mask arrives.
        first = self._landing_layer(store)
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
        if self._mask_thread is not None:
            self._mask_thread.quit()
            self._mask_thread.wait(3000)
