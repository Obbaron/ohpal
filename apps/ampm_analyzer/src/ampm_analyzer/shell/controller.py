"""Application controller — the bridge between widgets and ohpal.

Owns the ``BuildSession`` and all threading. Widget signals call controller
methods; the controller talks to ohpal (heavy work off-thread) and writes the
session, which emits change signals the window reacts to. The controller never
touches widgets except to raise file dialogs (main-thread, modal).
"""

from __future__ import annotations

import re
from pathlib import Path

from PyQt6.QtCore import QObject, QThread
from PyQt6.QtWidgets import QFileDialog, QWidget

from .state import BuildSession
from .workers import QueryWorker

# Same packet-filename shape the DataStore expects.
_PACKET_RE = re.compile(r"^Packet data for layer \d+, laser \d+\.txt$", re.IGNORECASE)

# Stage 1: cap the rows handed to the (non-virtualised) grid. The full
# virtualised model lands in Stage 3.
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
        self._worker: QueryWorker | None = None
        self._busy = False

    # -- entry points --------------------------------------------------
    def load_build(self) -> None:
        """Pick a build directory and load it. Single-flight."""
        if self._busy:
            return
        chosen = QFileDialog.getExistingDirectory(
            self._window, "Open AMPM build or packet directory"
        )
        if not chosen:
            return
        self.load_path(Path(chosen))

    def load_path(self, path: Path) -> None:
        """Load a known directory (used by the picker and, later, recents)."""
        if self._busy:
            return
        self._busy = True
        self.session.begin_load(path.name)
        try:
            source_dir, layer_thickness, build_name = self._resolve_build(path)
            store = self._construct_store(source_dir, layer_thickness)
        except Exception as exc:  # noqa: BLE001 - report, don't crash
            self._busy = False
            self.session.fail(str(exc))
            return

        self.session.set_store(store, source_dir, build_name, layer_thickness)
        first = store.layers[0]
        self._start_query(store, (first, first))

    # -- build resolution ----------------------------------------------
    def _resolve_build(self, path: Path) -> tuple[Path, float, str]:
        """Return (packet_source_dir, layer_thickness, build_name).

        Accepts either the packet directory itself, a build root with a
        ``config.toml`` (source resolved from it), or a build root with a
        packet subdirectory.
        """
        if _has_packets(path):
            # The packet dir may sit inside a build root whose config sets the
            # layer thickness; fall back to the ohpal default otherwise.
            lt = self._thickness_from_config(path.parent)
            return path, lt, path.parent.name or path.name

        cfg = path / "config.toml"
        if cfg.exists():
            config = self._guarded_load_config(path)
            source = Path(config["SOURCE"])
            lt = float(config.get("LAYER_THICKNESS") or 0.03) or 0.03
            if not _has_packets(source):
                raise RuntimeError(
                    f"config.toml points at '{source}', but no packet files were "
                    f"found there."
                )
            return source, lt, path.name

        for sub in sorted(path.iterdir()):
            if sub.is_dir() and _has_packets(sub):
                return sub, self._thickness_from_config(path), path.name

        raise RuntimeError(
            "No 'Packet data for layer N, laser M.txt' files found in the chosen "
            "directory (or a config.toml / packet subfolder)."
        )

    def _thickness_from_config(self, build_dir: Path) -> float:
        cfg = build_dir / "config.toml"
        if not cfg.exists():
            return 0.03
        try:
            config = self._guarded_load_config(build_dir)
            return float(config.get("LAYER_THICKNESS") or 0.03) or 0.03
        except Exception:  # noqa: BLE001 - a bad config shouldn't block loading
            return 0.03

    @staticmethod
    def _guarded_load_config(build_dir: Path) -> dict:
        """Call ohpal's load_config, turning its sys.exit() into an exception."""
        from ohpal.ampm.config import load_config

        try:
            return load_config(build_dir)
        except SystemExit as exc:
            raise RuntimeError(f"Could not read config.toml: {exc}") from exc

    @staticmethod
    def _construct_store(source_dir: Path, layer_thickness: float):
        from ohpal.ampm import DataStore

        return DataStore(source_dir, layer_thickness=layer_thickness)

    # -- threaded query ------------------------------------------------
    def _start_query(self, store, layers: tuple[int, int]) -> None:
        thread = QThread(self)
        worker = QueryWorker(store, layers, row_cap=STAGE1_ROW_CAP)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.finished.connect(self._on_query_finished)
        worker.error.connect(self._on_query_error)
        # Teardown: stop the thread once the worker is done either way.
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_thread)

        self._thread = thread
        self._worker = worker
        thread.start()

    def _on_query_finished(self, result) -> None:
        self._busy = False
        self.session.set_result(result)

    def _on_query_error(self, message: str) -> None:
        self._busy = False
        self.session.fail(message)

    def _clear_thread(self) -> None:
        self._thread = None
        self._worker = None

    # -- shutdown ------------------------------------------------------
    def shutdown(self) -> None:
        """Stop any running worker thread cleanly on app close."""
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(3000)
