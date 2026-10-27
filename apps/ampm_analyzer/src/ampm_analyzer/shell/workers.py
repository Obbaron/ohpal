"""Background workers.

QObject workers moved onto a QThread (the modern pattern — not QThread
subclassed with logic in run()). Each worker exposes the standard contract:
``progress(int, str)``, ``finished(object)``, ``error(str)``.

Rules followed here: the worker never touches widgets; all results leave via
signals (delivered on the main thread); exceptions — including the ``SystemExit``
that ohpal's config helpers can raise — become ``error`` signals rather than
killing anything.
"""

from __future__ import annotations

import traceback
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from .state import QueryResult


class QueryWorker(QObject):
    """Runs ``DataStore.query`` off the UI thread (Stage 1: query path only).

    The first query of an uncached layer bakes that layer's parquet, which is
    why this runs in a thread. Progress is coarse (query is a single ohpal
    call); finer per-layer progress arrives with the build_cache work later.
    """

    progress = pyqtSignal(int, str)
    finished = pyqtSignal(object)  # QueryResult
    error = pyqtSignal(str)

    def __init__(
        self,
        store: Any,
        layers: tuple[int, int],
        *,
        columns: list[str] | None = None,
        row_cap: int | None = None,
    ) -> None:
        super().__init__()
        self._store = store
        self._layers = layers
        self._columns = columns
        self._row_cap = row_cap

    @pyqtSlot()
    def run(self) -> None:
        try:
            lo, hi = self._layers
            self.progress.emit(0, f"Querying layer {lo}…")
            df = self._store.query(layers=self._layers, columns=self._columns)
            total = df.height
            if self._row_cap is not None and total > self._row_cap:
                df = df.head(self._row_cap)
            self.progress.emit(100, "Loaded")
            self.finished.emit(
                QueryResult(
                    df=df,
                    total_rows=total,
                    shown_rows=df.height,
                    layers=self._layers,
                )
            )
        except SystemExit as exc:  # ohpal config helpers can call sys.exit()
            self.error.emit(f"Load aborted: {exc}")
        except Exception:  # noqa: BLE001 - surface any failure as a message
            self.error.emit(traceback.format_exc())


class CacheWorker(QObject):
    """Builds the parquet cache off-thread, one layer at a time.

    We drive the per-layer loop ourselves (``build_cache([L], force=…)`` each),
    rather than scraping ``verbose`` output, so progress is real and the build
    can be cancelled between layers. ``build_cache`` skips up-to-date layers
    quickly when ``force`` is False, so "build missing" is cheap.
    """

    progress = pyqtSignal(int, int, int)  # done, total, layer
    finished = pyqtSignal(int)  # number of layers (re)built
    error = pyqtSignal(str)

    def __init__(self, store: Any, layers: list[int], *, force: bool) -> None:
        super().__init__()
        self._store = store
        self._layers = list(layers)
        self._force = force
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @pyqtSlot()
    def run(self) -> None:
        try:
            total = len(self._layers)
            built = 0
            for i, layer in enumerate(self._layers, start=1):
                if self._cancelled:
                    break
                self._store.build_cache(
                    layers=[layer], force=self._force, verbose=False
                )
                built += 1
                self.progress.emit(i, total, layer)
            self.finished.emit(built)
        except SystemExit as exc:
            self.error.emit(f"Build aborted: {exc}")
        except Exception:  # noqa: BLE001
            self.error.emit(traceback.format_exc())
