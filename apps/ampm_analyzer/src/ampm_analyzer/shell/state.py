"""Session state — the single source of truth for a loaded build.

``BuildSession`` holds the active ``DataStore`` and the most recent query
result, and emits Qt signals when they change. Widgets never reach into the
controller or ohpal; they react to these signals (on the main thread) and read
the session's attributes. The controller is the only writer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal


@dataclass
class QueryResult:
    """One query's output, plus the context the UI needs to describe it."""

    df: Any  # polars.DataFrame (kept untyped so state.py needn't import polars)
    total_rows: int  # rows in the queried slice before any display cap
    shown_rows: int  # rows actually handed to the grid (after the cap)
    layers: tuple[int, int]  # inclusive (lo, hi) of the queried layers


class BuildSession(QObject):
    """Mutable state for the active build, with change notifications."""

    # A load/query cycle has started (payload: a short human label).
    loadStarted = pyqtSignal(str)
    # A DataStore was constructed for a build (payload: the DataStore).
    buildLoaded = pyqtSignal(object)
    # The build needs setup before it can be shown — show the DataStore page
    # (payload: (config dict, layers list, exists bool)).
    setupRequired = pyqtSignal(object)
    # Per-layer cache-build progress (payload: (done, total, layer)).
    cacheProgress = pyqtSignal(int, int, int)
    # A query finished (payload: QueryResult).
    queryReady = pyqtSignal(object)
    # A load or query failed (payload: a human-readable message).
    loadFailed = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self.store: Any | None = None  # ohpal.ampm.DataStore
        self.source_dir: Path | None = None
        self.build_name: str = ""
        self.layer_thickness: float = 0.03
        self.result: QueryResult | None = None
        self.current_layer: int | None = None
        # Derived columns, re-applied to every query result (see shell/derive.py).
        # Controller-owned.
        self.derivations: list[dict] = []
        # Source columns removed from the view — projected out of every result
        # (distinct from hiding, which keeps them in the data). Controller-owned.
        self.removed: list[str] = []

    # -- writers (controller-only) -------------------------------------
    def begin_load(self, label: str) -> None:
        self.loadStarted.emit(label)

    def set_store(
        self, store: Any, source_dir: Path, build_name: str, layer_thickness: float
    ) -> None:
        self.store = store
        self.source_dir = source_dir
        self.build_name = build_name
        self.layer_thickness = layer_thickness
        self.result = None
        self.derivations = []  # derived columns don't carry across builds
        self.removed = []
        self.buildLoaded.emit(store)

    def require_setup(
        self, config: dict, layers: list, columns: list, exists: bool
    ) -> None:
        self.setupRequired.emit((config, layers, columns, exists))

    def cache_progress(self, done: int, total: int, layer: int) -> None:
        self.cacheProgress.emit(done, total, layer)

    def set_result(self, result: QueryResult) -> None:
        self.result = result
        self.queryReady.emit(result)

    def fail(self, message: str) -> None:
        self.loadFailed.emit(message)

    @property
    def has_build(self) -> bool:
        return self.store is not None
