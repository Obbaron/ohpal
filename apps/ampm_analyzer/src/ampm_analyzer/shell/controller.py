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
        self._pending_span: tuple[int, int] | None = None
        self._base_df = None  # last raw query output, before derived columns

    # -- entry points --------------------------------------------------
    def new_build(self) -> None:
        self._start("new")

    def open_build(self) -> None:
        self._start("open")

    def _start(self, mode: str) -> None:
        if self._busy:
            return
        title = "Prepare a new build" if mode == "new" else "Open a prepared build"
        chosen = QFileDialog.getExistingDirectory(self._window, title)
        if not chosen:
            return
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
        self.session.set_store(store, source_dir, build_root.name, thickness)

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
    def build_datastore(self, scope: tuple[int, int] | None) -> None:
        store = self.session.store
        if store is None or self._busy:
            return
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

    @staticmethod
    def _cache_status(store) -> tuple[int, int]:
        cached = sum(1 for L in store.layers if store._cache_path(L).exists())
        return cached, len(store.layers)

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

    # -- span navigation (the shared working span) ---------------------
    def set_span(self, mode: str, lo: int | None = None, hi: int | None = None) -> None:
        """Set the shared span the grid and all plots see (pending-latest).

        ``mode`` is "single", "range" or "all". Bounds snap to real layers.
        """
        store = self.session.store
        if store is None:
            return
        layers = store.layers

        def _snap(v):
            return min(layers, key=lambda L: abs(L - v))

        if mode == "all":
            qlo, qhi = layers[0], layers[-1]
        elif mode == "range":
            lo = _snap(lo if lo is not None else layers[0])
            hi = _snap(hi if hi is not None else layers[-1])
            qlo, qhi = (lo, hi) if lo <= hi else (hi, lo)
        else:  # single
            qlo = qhi = _snap(lo if lo is not None else layers[0])

        self.session.span_mode = mode
        self.session.span_range = (qlo, qhi)
        if (
            self.session.result is not None
            and self.session.result.layers == (qlo, qhi)
        ):
            return  # already showing this span
        self._pending_span = (qlo, qhi)
        if not self._busy:
            self._run_pending()

    def _run_pending(self) -> None:
        if self._pending_span is None:
            return
        lo, hi = self._pending_span
        self._pending_span = None
        label = f"layer {lo}" if lo == hi else f"layers {lo}–{hi}"
        self.session.begin_load(label)
        self._start_query(self.session.store, (lo, hi))

    # -- threaded query ------------------------------------------------
    def _begin_query(self, store) -> None:
        first = store.layers[0]
        self.session.span_mode = "single"
        self.session.span_range = (first, first)
        self._start_query(store, (first, first))

    def _start_query(self, store, layers: tuple[int, int]) -> None:
        self._busy = True
        thread = QThread(self)
        worker = QueryWorker(store, layers, row_cap=None)  # virtualised grid: no cap
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
        self.session.current_layer = result.layers[0]
        self._base_df = result.df  # keep the raw output for re-deriving
        self.session.set_result(self._pipeline(result))
        self._run_pending()  # a layer change requested while we were busy

    # -- column pipeline (derive, then drop removed) -------------------
    def _pipeline(self, template: QueryResult) -> QueryResult:
        """Build the display frame from the raw base: add derived columns, then
        project out removed source columns. ``template`` supplies the row/layer
        metadata (unaffected by column changes)."""
        df = self._base_df
        if self.session.derivations:
            df = derive.apply(df, self.session.derivations)
        drop = [c for c in self.session.removed if c in df.columns]
        if drop:
            df = df.drop(drop)  # derived cols that used them are already computed
        return QueryResult(df, template.total_rows, template.shown_rows, template.layers)

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
        self.session.set_result(self._pipeline(self.session.result))

    def _on_cache_finished(self, store) -> None:
        # Cache built — now show the first layer.
        first = store.layers[0]
        self.session.span_mode = "single"
        self.session.span_range = (first, first)
        self._start_query(store, (first, first))

    def _on_worker_error(self, message: str) -> None:
        self._busy = False
        self.session.fail(message)

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
