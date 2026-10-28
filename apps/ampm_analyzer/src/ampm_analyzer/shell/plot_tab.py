"""Plot tab — a dumb VisPy scatter bound to the shared result.

Holds a PlotSpec (which columns map to X/Y/Z/colour) and renders whatever
dataframe it's handed. The window re-feeds it the shared result whenever the
span or data changes; the tab never queries or assumes columns.

Decorations:
  * 2D → ticked AxisWidgets (column names as titles) + optional gridlines.
  * 3D → a wireframe bounding box + coloured axis-name labels at the box edges.
  * numeric colour → a ColorBarWidget; the toolbar toggles show/hide each.

VisPy is imported lazily and guarded: without it (or an OpenGL context) the tab
shows a labelled placeholder. Render arrays are released on close.
"""

from __future__ import annotations

import numpy as np
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from . import plotdata
from .plotdata import DEFAULT_COLORMAP, colormap_stops
from .plotspec import PlotSpec

_BG = "#e5ecf6"  # soft blue-grey (Plotly-style) so sparse points still read
# Axis label colours (x, y, z) for the 3D decorations.
_AXIS_RGB = ((0.80, 0.12, 0.12, 1), (0.10, 0.55, 0.12, 1), (0.12, 0.30, 0.85, 1))

# Marker sizing. Base is the on-screen px at/below the fit zoom; when zoomed out
# past the fit the size grows (×FIT→×MAX) so sparse struts fill in, easing back
# to base as you zoom in. 2D only — 3D keeps a fixed size.
_DEFAULT_MARKER_PX = 7
_SIZE_FIT_MULT = 1.6
_SIZE_MAX_MULT = 3.0


def _nice_step(span: float, target: int = 10) -> float:
    """A round grid step (1/2/5 × 10ⁿ) giving roughly `target` divisions."""
    if span <= 0:
        return 1.0
    raw = span / target
    mag = 10 ** np.floor(np.log10(raw))
    norm = raw / mag
    step = 1 if norm < 1.5 else 2 if norm < 3 else 5 if norm < 7 else 10
    return step * mag


def _grid_range(a0: float, a1: float, step: float) -> np.ndarray:
    """Grid-line positions on `step` within [a0, a1]."""
    start = np.ceil(a0 / step) * step
    return np.arange(start, a1 + step * 0.5, step)


# How far the 3D floor grid extends past the data, as a fraction of each span.
_FLOOR_PAD = 0.5


def _fmt(v) -> str:
    """Compact value formatting for the hover tooltip."""
    if isinstance(v, float):
        return f"{v:.4g}"
    return str(v)


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
        self._data_bounds = None  # (lo, hi) of the data, for framing the camera

        # Decoration toggles. Grid on by default for both (2D gridlines / 3D
        # floor); the bounding box is 3D-only.
        self._show_axes = True
        self._show_grid = True
        self._show_bbox = spec.is_3d
        self._show_legend = True

        self._canvas = None
        self._view = None
        self._scatter = None
        self._grid = None
        self._cbar_col = 2
        self._xaxis = self._yaxis = None
        self._gridlines = None  # 2D screen-aligned gridlines
        self._floor = None      # 3D grid on the X-Y plane
        self._cbar = None
        self._bbox = None
        self._axis_labels: list = []
        self._status: QLabel | None = None

        # Hover tooltip (2D only): a KDTree over the drawn points + the rows
        # behind them, and a floating label shown near the cursor.
        self._hover_tree = None
        self._hover_xy = None
        self._hover_rows = None
        self._tooltip: QLabel | None = None

        # Marker sizing / zoom-adaptive state.
        self._base_size = _DEFAULT_MARKER_PX   # slider-driven base px
        self._applied_size: float | None = None  # last px set on the scatter
        self._fit_width: float | None = None   # visible data width at fit (2D)
        self._last_pos = None                   # drawn positions (for re-sizing)
        self._last_colors = None

        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._body = self._build_canvas()
        self._lay.addWidget(self._body)

    @property
    def span_label(self) -> str:
        mode, lo, hi = self.span
        if mode == "all":
            return "all layers"
        return f"layer {lo}" if lo == hi else f"layers {lo}–{hi}"

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
            canvas = scene.SceneCanvas(keys="interactive", bgcolor=_BG, show=False)
            grid = canvas.central_widget.add_grid(margin=6)
            self._grid = grid
            if self.spec.is_3d:
                # No left axis column in 3D — an empty grid column would take an
                # equal stretch and shove the view into the right half. View at
                # col 0, colourbar at col 1.
                view = grid.add_view(row=0, col=0)
                view.camera = scene.cameras.TurntableCamera(fov=45)
                self._cbar_col = 1
            else:
                view = grid.add_view(row=0, col=1)
                # aspect=1 → one X unit == one Y unit, so parts aren't skewed.
                view.camera = scene.cameras.PanZoomCamera(aspect=1)
                self._cbar_col = 2
                self._yaxis = scene.AxisWidget(
                    orientation="left", axis_label=self.spec.y,
                    axis_font_size=9, tick_label_margin=12,
                )
                self._yaxis.width_max = 62
                grid.add_widget(self._yaxis, row=0, col=0)
                self._xaxis = scene.AxisWidget(
                    orientation="bottom", axis_label=self.spec.x,
                    axis_font_size=9, tick_label_margin=12,
                )
                self._xaxis.height_max = 42
                grid.add_widget(self._xaxis, row=1, col=1)
                self._yaxis.link_view(view)
                self._xaxis.link_view(view)
                self._gridlines = scene.visuals.GridLines(
                    color=(0, 0, 0, 0.12), parent=view.scene
                )
                self._gridlines.visible = self._show_grid
            self._scatter = scene.visuals.Markers()
            view.add(self._scatter)
            self._canvas, self._view = canvas, view
            canvas.events.mouse_move.connect(self._on_mouse_move)
            canvas.events.mouse_wheel.connect(self._on_wheel)
            return canvas.native
        except Exception as exc:  # noqa: BLE001 - GL context failure -> placeholder
            return _placeholder(f"Could not start the canvas:\n{exc}")

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
        if self.crange is None and data.crange is not None:
            self.crange = data.crange  # auto-detect once; sliders tweak after
        first = not self._rendered_once
        self._rendered_once = True
        self._last_pos, self._last_colors = data.pos, data.colors
        self._set_scatter(self._effective_size())
        self._build_hover_index(data)
        self._update_decor(data)
        self._apply_visibility()
        if self._view is not None and first:
            # Defer the fit so the grid (incl. the just-added colourbar) has
            # settled and the view has its real size before framing.
            QTimer.singleShot(0, self.reset_view)

    # -- decorations ---------------------------------------------------
    def _update_decor(self, data) -> None:
        if data.n_drawn:
            lo, hi = data.pos.min(axis=0), data.pos.max(axis=0)
            self._data_bounds = (lo, hi)
            if self.spec.is_3d:
                self._build_3d_axes(lo, hi)
        self._update_legend(data)

    def _build_3d_axes(self, lo, hi) -> None:
        from vispy import scene

        for old in [self._bbox, self._floor, *self._axis_labels]:
            if old is not None:
                old.parent = None
        self._axis_labels = []
        self._floor = None

        x0, y0, z0 = (float(v) for v in lo)
        x1, y1, z1 = (float(v) for v in hi)
        c = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
             (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
        e = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4),
             (0, 4), (1, 5), (2, 6), (3, 7)]
        segs = np.array([c[i] for pair in e for i in pair], dtype="float32")
        self._bbox = scene.visuals.Line(segs, connect="segments",
                                        color=(0, 0, 0, 0.30),
                                        parent=self._view.scene)
        self._floor = self._build_floor(x0, x1, y0, y1, z0)
        labels = [
            (self.spec.x, ((x0 + x1) / 2, y0, z0)),
            (self.spec.y, (x0, (y0 + y1) / 2, z0)),
            (self.spec.z, (x0, y0, (z0 + z1) / 2)),
        ]
        for i, (name, p) in enumerate(labels):
            t = scene.visuals.Text(name, pos=p, color=_AXIS_RGB[i],
                                   font_size=10, bold=True,
                                   parent=self._view.scene)
            self._axis_labels.append(t)

    def _build_floor(self, x0, x1, y0, y1, z0):
        """A grid on the X-Y plane at z=z0 extending past the data.

        Cell size follows the data span (nice 1/2/5 step), but the grid is
        padded out by ``_FLOOR_PAD`` of each span so it reads as a ground plane.
        """
        from vispy import scene

        xspan, yspan = (x1 - x0) or 1.0, (y1 - y0) or 1.0
        ex0, ex1 = x0 - _FLOOR_PAD * xspan, x1 + _FLOOR_PAD * xspan
        ey0, ey1 = y0 - _FLOOR_PAD * yspan, y1 + _FLOOR_PAD * yspan
        stepx, stepy = _nice_step(xspan), _nice_step(yspan)
        xs = _grid_range(ex0, ex1, stepx)
        ys = _grid_range(ey0, ey1, stepy)
        segs = []
        for gx in xs:
            segs += [(gx, ey0, z0), (gx, ey1, z0)]
        for gy in ys:
            segs += [(ex0, gy, z0), (ex1, gy, z0)]
        if not segs:
            return None
        line = scene.visuals.Line(np.array(segs, dtype="float32"),
                                  connect="segments", color=(0, 0, 0, 0.14),
                                  parent=self._view.scene)
        line.visible = self._show_grid
        return line

    def _update_legend(self, data) -> None:
        leg = data.legend
        if isinstance(leg, tuple) and leg and leg[0] == "colorbar":
            _, lo, hi, name = leg
            self._set_colorbar(lo, hi, name)
        elif self._cbar is not None:
            self._cbar.visible = False  # categorical/none: no colourbar (yet)

    def _set_colorbar(self, lo, hi, name) -> None:
        from vispy import scene
        from vispy.color import Colormap

        cm = Colormap(colormap_stops(self.cmap))
        if self._cbar is None:
            self._cbar = scene.ColorBarWidget(
                cmap=cm, orientation="right", label=str(name),
                clim=(float(lo), float(hi)), border_width=1,
                border_color="#888888",
            )
            self._cbar.width_max = 80
            self._grid.add_widget(self._cbar, row=0, col=self._cbar_col)
        else:
            self._cbar.cmap = cm
            self._cbar.clim = (float(lo), float(hi))
            self._cbar.label.text = str(name)
        self._cbar.visible = self._show_legend

    def _apply_visibility(self) -> None:
        for w in (self._xaxis, self._yaxis):
            if w is not None:
                w.visible = self._show_axes
        if self._gridlines is not None:
            self._gridlines.visible = self._show_grid
        if self._floor is not None:
            self._floor.visible = self._show_grid
        if self._bbox is not None:
            self._bbox.visible = self._show_bbox
        for t in self._axis_labels:
            t.visible = self._show_axes
        if self._cbar is not None:
            self._cbar.visible = self._show_legend

    # -- toolbar-driven controls ---------------------------------------
    def set_axes_visible(self, on: bool) -> None:
        self._show_axes = on
        self._apply_visibility()

    def set_grid_visible(self, on: bool) -> None:
        self._show_grid = on
        self._apply_visibility()

    def set_bbox_visible(self, on: bool) -> None:
        self._show_bbox = on
        self._apply_visibility()

    def set_legend_visible(self, on: bool) -> None:
        self._show_legend = on
        self._apply_visibility()

    def reset_view(self) -> None:
        if self._view is None:
            return
        b = self._data_bounds
        if b is None:  # fall back to the whole scene
            self._view.camera.set_range(margin=0.12)
            return
        lo, hi = b  # frame the data, not the padded floor grid
        if self.spec.is_3d:
            self._view.camera.set_range(x=(lo[0], hi[0]), y=(lo[1], hi[1]),
                                        z=(lo[2], hi[2]), margin=0.12)
        else:
            self._view.camera.set_range(x=(lo[0], hi[0]), y=(lo[1], hi[1]),
                                        margin=0.12)
            # Record the fit width as the zoom-adaptive reference, then size.
            try:
                self._fit_width = float(self._view.camera.rect.width)
            except Exception:  # noqa: BLE001
                self._fit_width = None
            self._resize_markers()

    # -- marker sizing (zoom-adaptive, 2D) -----------------------------
    def _effective_size(self) -> float:
        """On-screen px for the markers: base, grown when zoomed out (2D)."""
        if self.spec.is_3d or self._view is None or not self._fit_width:
            return self._base_size
        try:
            w = float(self._view.camera.rect.width)
        except Exception:  # noqa: BLE001
            return self._base_size
        if w <= 0:
            return self._base_size
        mult = min(_SIZE_MAX_MULT, max(1.0, _SIZE_FIT_MULT * w / self._fit_width))
        return self._base_size * mult

    def _set_scatter(self, px: float) -> None:
        if self._scatter is None or self._last_pos is None:
            return
        self._scatter.set_data(self._last_pos, face_color=self._last_colors,
                               size=px, edge_width=0, edge_color=None)
        self._applied_size = px

    def _resize_markers(self) -> None:
        """Re-apply the adaptive size if the zoom changed it meaningfully."""
        px = self._effective_size()
        if self._applied_size is None or abs(px - self._applied_size) >= 0.5:
            self._set_scatter(px)

    def _on_wheel(self, event) -> None:
        # Defer so the camera has applied the zoom before we read its rect.
        QTimer.singleShot(0, self._resize_markers)

    def set_marker_size(self, px: int) -> None:
        """Set the base marker size (from the Size slider)."""
        self._base_size = max(1, int(px))
        self._set_scatter(self._effective_size())

    def marker_size(self) -> int:
        return self._base_size

    def toggle_states(self) -> dict:
        return {
            "axes": self._show_axes, "grid": self._show_grid,
            "bbox": self._show_bbox, "legend": self._show_legend,
            "is_3d": self.spec.is_3d,
        }

    # -- overlay (errors / empty) on top of the canvas -----------------
    def _show_overlay(self, text: str) -> None:
        if self._scatter is not None:
            self._scatter.set_data(np.zeros((0, 3), "float32"))
        if self._status is None:
            self._status = QLabel(self)
            self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._status.setStyleSheet("color:#5a6472; font-size:13px;")
            self._status.setWordWrap(True)
            self._lay.addWidget(self._status)
        self._status.setText(text)
        self._status.setVisible(True)

    def _clear_overlay(self) -> None:
        if self._status is not None:
            self._status.setVisible(False)

    # -- hover tooltip (2D) --------------------------------------------
    def _build_hover_index(self, data) -> None:
        """Spatial index over the drawn points for nearest-point hover (2D)."""
        if self.spec.is_3d or data.rows is None or data.n_drawn == 0:
            self._hover_tree = self._hover_rows = self._hover_xy = None
            self._hide_tooltip()
            return
        try:
            from scipy.spatial import cKDTree

            self._hover_xy = np.ascontiguousarray(data.pos[:, :2], dtype="float64")
            self._hover_tree = cKDTree(self._hover_xy)
            self._hover_rows = data.rows
        except Exception:  # noqa: BLE001 - hover is a nicety; never break render
            self._hover_tree = self._hover_rows = self._hover_xy = None

    def _on_mouse_move(self, event) -> None:
        if (
            self._hover_tree is None
            or self._scatter is None
            or getattr(event, "pos", None) is None
        ):
            return
        if getattr(event, "buttons", None):  # a drag (pan/zoom) — not a hover
            self._hide_tooltip()
            self._resize_markers()  # right-drag zoom changes the scale
            return
        try:
            to_data = self._scatter.get_transform("canvas", "visual")
            dx, dy = to_data.map(event.pos)[:2]
            _, i = self._hover_tree.query([dx, dy])
            # Accept only within a few pixels of the point (zoom-independent).
            to_canvas = self._scatter.get_transform("visual", "canvas")
            px, py = to_canvas.map(
                [self._hover_xy[i][0], self._hover_xy[i][1]]
            )[:2]
            if (px - event.pos[0]) ** 2 + (py - event.pos[1]) ** 2 > 12 ** 2:
                self._hide_tooltip()
                return
            self._show_tooltip(int(i))
        except Exception:  # noqa: BLE001
            self._hide_tooltip()

    def _hover_text(self, i: int) -> str:
        rows = self._hover_rows
        if rows is None or i < 0 or i >= rows.height:
            return ""
        cols = list(dict.fromkeys(
            [*self.spec.axes]
            + ([self.spec.color] if self.spec.color else [])
            + [c for c in ("part_id", "layer") if c in rows.columns]
        ))
        row = rows.row(i, named=True)
        return "\n".join(f"{c}: {_fmt(row.get(c))}" for c in cols)

    def _show_tooltip(self, i: int) -> None:
        text = self._hover_text(i)
        if not text or self._canvas is None:
            self._hide_tooltip()
            return
        from PyQt6.QtGui import QCursor

        if self._tooltip is None:
            self._tooltip = QLabel(self._canvas.native)
            self._tooltip.setStyleSheet(
                "background: rgba(28,32,38,0.92); color: #f2f4f7;"
                " border-radius: 4px; padding: 5px 7px; font-size: 11px;"
            )
            self._tooltip.setTextFormat(Qt.TextFormat.PlainText)
        self._tooltip.setText(text)
        self._tooltip.adjustSize()
        native = self._canvas.native
        p = native.mapFromGlobal(QCursor.pos())
        w, h = self._tooltip.width(), self._tooltip.height()
        x = min(p.x() + 14, native.width() - w - 4)
        y = min(p.y() + 14, native.height() - h - 4)
        self._tooltip.move(max(0, x), max(0, y))
        self._tooltip.show()
        self._tooltip.raise_()

    def _hide_tooltip(self) -> None:
        if self._tooltip is not None:
            self._tooltip.hide()

    # -- teardown ------------------------------------------------------
    def release(self) -> None:
        """Free render arrays and close the canvas (called on tab close)."""
        self._df = None
        self.raw = None
        self._scatter = None
        self._view = None
        self._hover_tree = self._hover_rows = self._hover_xy = None
        self._last_pos = self._last_colors = None
        self._hide_tooltip()
        if self._canvas is not None:
            try:
                self._canvas.close()
            except Exception:  # noqa: BLE001
                pass
            self._canvas = None
