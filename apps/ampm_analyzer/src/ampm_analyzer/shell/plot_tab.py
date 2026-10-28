"""Plot tab — a dumb VisPy scatter bound to the shared result.

Holds a PlotSpec (which columns map to X/Y/Z/colour) and renders whatever
dataframe it's handed. The window re-feeds it the shared result whenever the
span or data changes; the tab never queries or assumes columns.

VisPy is imported lazily and guarded: without VisPy (or an OpenGL context) the
tab shows a labelled placeholder instead of crashing, so the shell runs anywhere.
Render arrays are released on close.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from . import plotdata
from .plotdata import DEFAULT_COLORMAP
from .plotspec import PlotSpec

_BG = "white"  # plot canvas background


def _placeholder(message: str) -> QWidget:
    frame = QFrame()
    frame.setStyleSheet("background:#f4f5f7;")
    lay = QVBoxLayout(frame)
    lab = QLabel(message)
    lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lab.setStyleSheet("color:#5a6472; font-size:14px;")
    lab.setWordWrap(True)
    lay.addWidget(lab)
    return frame


class PlotTab(QWidget):
    _counter = 0

    def __init__(self, spec: PlotSpec, span=None, title: str | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("tabkind", "plot")
        PlotTab._counter += 1
        self.spec = spec
        self.span = span or ("all", None, None)
        self.title = title or f"{spec.kind} {PlotTab._counter}"

        self._df = None
        self.raw = None  # the plot's own raw span query (for re-shaping)
        self.cmap = DEFAULT_COLORMAP
        self.scale = "linear"
        self.crange = None  # auto-detected on first render; sliders then tweak
        self._rendered_once = False
        self._canvas = None
        self._view = None
        self._scatter = None
        self._status: QLabel | None = None

        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._body = self._build_canvas()
        self._lay.addWidget(self._body)

    @property
    def span_label(self) -> str:
        mode, lo, hi = self.span
        return "all layers" if mode == "all" else f"layers {lo}–{hi}"

    def set_loading(self, text: str) -> None:
        self._show_overlay(text)

    # -- canvas --------------------------------------------------------
    def _build_canvas(self) -> QWidget:
        try:
            from vispy import scene
        except Exception as exc:  # noqa: BLE001 - import failure -> placeholder
            return _placeholder(
                "3D plotting needs VisPy, which isn't installed in this Python.\n\n"
                "Install it, then reopen the plot:\n    pip install vispy\n\n"
                f"(import error: {exc})"
            )
        try:
            canvas = scene.SceneCanvas(keys="interactive", bgcolor=_BG,
                                       show=False)
            view = canvas.central_widget.add_view()
            if self.spec.is_3d:
                view.camera = scene.cameras.TurntableCamera(fov=45)
                scene.visuals.XYZAxis(parent=view.scene)
            else:
                view.camera = scene.cameras.PanZoomCamera(aspect=None)
            self._scatter = scene.visuals.Markers()
            view.add(self._scatter)
            self._canvas, self._view = canvas, view
            return canvas.native
        except Exception as exc:  # noqa: BLE001 - GL context failure -> placeholder
            return _placeholder(f"Could not start the 3D canvas:\n{exc}")

    # -- data ----------------------------------------------------------
    def set_dataframe(self, df) -> None:
        """(Re)render with a new dataframe, keeping the same spec."""
        self._df = df
        self._render()

    def _render(self) -> None:
        if self._df is None or self._scatter is None:
            return
        try:
            data = plotdata.build(self._df, self.spec, cmap=self.cmap,
                                  scale=self.scale, crange=self.crange)
        except KeyError as exc:  # a spec column isn't in the data any more
            self._show_overlay(str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            self._show_overlay(f"Could not plot: {exc}")
            return

        if data.n_drawn == 0:
            self._show_overlay("No rows to plot for this selection.")
            return
        self._clear_overlay()
        # Auto-detect the colour range on the first render; sliders tweak after.
        if self.crange is None and data.crange is not None:
            self.crange = data.crange
        first = not self._rendered_once
        self._rendered_once = True
        self._scatter.set_data(data.pos, face_color=data.colors, size=5,
                               edge_width=0)
        if self._view is not None and first:
            self._view.camera.set_range(margin=0.12)  # fit all data + buffer

    # -- overlay (errors / empty) on top of the canvas -----------------
    def _show_overlay(self, text: str) -> None:
        if self._scatter is not None:
            import numpy as np

            self._scatter.set_data(np.zeros((0, 3), "float32"))
        if self._status is None:
            self._status = QLabel(self)
            self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._status.setStyleSheet("color:#8b93a1; font-size:13px;")
            self._status.setWordWrap(True)
            self._lay.addWidget(self._status)
        self._status.setText(text)
        self._status.setVisible(True)

    def _clear_overlay(self) -> None:
        if self._status is not None:
            self._status.setVisible(False)

    # -- teardown ------------------------------------------------------
    def release(self) -> None:
        """Free render arrays and close the canvas (called on tab close)."""
        self._df = None
        self._scatter = None
        self._view = None
        if self._canvas is not None:
            try:
                self._canvas.close()
            except Exception:  # noqa: BLE001
                pass
            self._canvas = None
