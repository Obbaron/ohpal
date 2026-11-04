"""A plot popped out into its own top-level window.

A detached plot is self-contained: it owns a frozen snapshot of everything it
depends on — the build's store handle, a copy of the session's derivations /
removed columns, and its row filter — so it keeps working (and re-querying)
after the main window moves to another build. That's what lets you line up
plots from different builds side by side.

Live re-query (a Layer Viewer scrubbing its slider) runs off-thread against the
held store. The store keeps the build's absolute cache path; if that cache ever
becomes unreachable the window keeps showing its last frame and says so, rather
than crashing.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QToolBar,
)

from . import derive, toolbars
from .dock import SidePanel
from .plot_tab import PlotTab


class DetachedPlotWindow(QMainWindow):
    """Hosts one PlotTab plus its toolbar and side panel, independent of the
    main window and its build."""

    closed = pyqtSignal(object)  # emits self so the owner can drop its reference
    dockRequested = pyqtSignal(object)  # emits self when "Dock in" is clicked

    def __init__(self, *, spec, span, layers, raw, appearance, context,
                 icon_color: str, parent=None) -> None:
        super().__init__(parent)
        # Frozen context: store handle + derivation/removed/filter snapshots.
        self._store = context.get("store")
        self._derivations = list(context.get("derivations") or [])
        self._removed = list(context.get("removed") or [])
        self._row_filter = list(context.get("row_filter") or [])
        self._renames = dict(context.get("renames") or {})
        self._build_name = context.get("build_name") or "build"
        self._icon_color = icon_color
        self._thread = None
        self._worker = None

        self._tab = PlotTab(spec, span=span, layers=layers)
        self._tab.row_filter = self._row_filter
        self._tab.apply_appearance(appearance)
        self.setWindowTitle(f"{self._build_name} — {self._tab.title}")

        self._panel = SidePanel()
        self._panel.setVisible(False)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self._panel)
        split.addWidget(self._tab)
        split.setStretchFactor(1, 1)
        self.setCentralWidget(split)

        self._toolbar = QToolBar()
        self._toolbar.setMovable(False)
        self.addToolBar(self._toolbar)
        self._build_toolbar()
        self._wire_panel()

        self._tab.titleChanged.connect(self._on_renamed)
        if spec.is_layer_viewer:
            self._tab.layerChanged.connect(self._scrub)

        self._feed(raw)  # render immediately from the handed-over frame
        self.resize(860, 640)

    # -- toolbar / panel ----------------------------------------------
    def _build_toolbar(self) -> None:
        t = self._tab
        toolbars.populate_plot(
            self._toolbar,
            color=self._icon_color,
            sidebar_open=False,
            on_toggle_sidebar=self._toggle_panel,
            states=t.toggle_states(),
            on_reset_view=t.reset_view,
            on_axes=t.set_axes_visible,
            on_grid=t.set_grid_visible,
            on_bbox=t.set_bbox_visible,
            on_legend=t.set_legend_visible,
            on_title=t.set_title_visible,
            on_screenshot=self._screenshot,
            on_dock=self._request_dock,  # re-dock into the main window as a tab
            # no on_popout — a detached plot is already its own window
        )

    def _request_dock(self) -> None:
        self.dockRequested.emit(self)

    def dock_payload(self) -> dict:
        """Everything the main window needs to re-create this plot as a tab."""
        return {
            "spec": self._tab.spec,
            "span": self._tab.span,
            "layers": list(self._tab._layers),
            "raw": self._tab.raw,
            "appearance": self._tab.appearance(),
            "context": {
                "store": self._store,
                "build_name": self._build_name,
                "derivations": self._derivations,
                "removed": self._removed,
                "row_filter": self._row_filter,
                "renames": self._renames,
            },
        }

    def _wire_panel(self) -> None:
        p, t = self._panel, self._tab
        p.markerSizeChanged.connect(t.set_marker_size)
        p.markerSymbolChanged.connect(t.set_marker_symbol)
        p.opacityChanged.connect(t.set_opacity)
        p.colormapChanged.connect(t.set_colormap)
        p.scaleChanged.connect(t.set_scale)
        p.colorMinChanged.connect(t.set_color_min)
        p.colorMaxChanged.connect(t.set_color_max)
        p.closed.connect(lambda: p.setVisible(False))

    def _toggle_panel(self, on: bool) -> None:
        if on:
            self._panel.show_for("plot")
            self._panel.sync_plot(self._tab.panel_state())
        self._panel.setVisible(on)

    # -- data ----------------------------------------------------------
    def _feed(self, raw) -> None:
        self._tab.raw = raw
        self._tab.set_renames(self._renames)  # resolve hover extras
        shaped = derive.shape(raw, self._derivations, self._removed,
                              self._row_filter, self._renames)
        self._tab.set_dataframe(shaped)
        if self._panel.isVisible():
            self._panel.sync_plot(self._tab.panel_state())

    def _scrub(self, layer: int) -> None:
        self._tab.span = ("single", layer, layer)
        self._query(layer, layer)

    def _query(self, lo: int, hi: int) -> None:
        if self._store is None or self._thread is not None:
            return  # no store, or a query is already running — drop this one
        from .controller import _PLOT_SAMPLE_ROWS
        from .workers import QueryWorker

        thread = QThread(self)
        worker = QueryWorker(self._store, (lo, hi), columns=None,
                             sample_to=_PLOT_SAMPLE_ROWS)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_query_done)
        worker.error.connect(self._on_query_error)
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_thread)
        self._thread, self._worker = thread, worker
        thread.start()

    def _clear_thread(self) -> None:
        self._thread = self._worker = None

    def _on_query_done(self, result) -> None:
        self._feed(result.df)

    def _on_query_error(self, _msg: str) -> None:
        # Keep-path strategy: the cache became unreachable. Keep the last frame
        # and tell the user rather than crash (copy-on-demand would go here).
        self.statusBar().showMessage(
            "Couldn't re-query this build — showing the last layer.", 6000)

    # -- actions -------------------------------------------------------
    def _on_renamed(self, name: str) -> None:
        self.setWindowTitle(f"{self._build_name} — {name}")

    def _screenshot(self) -> None:
        safe = "".join(c if (c.isalnum() or c in " -_") else "_"
                       for c in self._tab.title).strip() or "plot"
        start = str(Path.home() / f"{safe}.png")
        path, selected = QFileDialog.getSaveFileName(
            self, "Save plot image", start,
            "PNG image (*.png);;JPEG image (*.jpg *.jpeg);;"
            "Bitmap (*.bmp);;TIFF image (*.tif *.tiff)",
        )
        if not path:
            return
        if not Path(path).suffix:
            path += {
                "JPEG image (*.jpg *.jpeg)": ".jpg",
                "Bitmap (*.bmp)": ".bmp",
                "TIFF image (*.tif *.tiff)": ".tif",
            }.get(selected, ".png")
        if self._tab.save_image(path):
            self.statusBar().showMessage(f"Saved {Path(path).name}", 4000)
        else:
            QMessageBox.warning(self, "Screenshot",
                                "Couldn't save the plot image.")

    # -- teardown ------------------------------------------------------
    def closeEvent(self, event) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(2000)
        try:
            self._tab.release()
        except Exception:  # noqa: BLE001
            pass
        self.closed.emit(self)
        super().closeEvent(event)
