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
from PyQt6.QtCore import Qt, QTimer, QPointF, QRectF
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
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

# Axis decoration colours: the domain line blends into the bg, ticks/labels
# stay faintly legible.
_AXIS_LINE = _BG
_AXIS_TICK = "#8a94a6"
_AXIS_TEXT = "#5a6472"


def _sig(x: float, n: int = 4) -> float:
    """Round to n significant figures (for compact colourbar labels)."""
    try:
        return float(f"{float(x):.{n}g}")
    except (ValueError, TypeError):
        return x


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


class PlotTooltip(QWidget):
    """Plotly-style hover bubble: filled with the hovered point's colour, with
    a triangle tail that points at the data point."""

    _PAD = 6
    _RADIUS = 5
    _TAIL = 9       # tail length (px)
    _TAILW = 12     # tail base width (px)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._lines: list[str] = []
        self._fill = QColor(40, 44, 52)
        self._text = QColor(245, 245, 245)
        self._below = False
        self._tipx = 0.0
        self._bubble = QRectF()
        self._font = QFont()
        self._font.setPointSize(9)
        self.hide()

    def show_at(self, tip, lines, rgba, host) -> None:
        self._lines = lines
        r, g, b = float(rgba[0]), float(rgba[1]), float(rgba[2])
        self._fill = QColor(int(max(0.0, min(1.0, r)) * 255),
                            int(max(0.0, min(1.0, g)) * 255),
                            int(max(0.0, min(1.0, b)) * 255))
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        self._text = QColor(20, 20, 20) if lum > 0.6 else QColor(245, 245, 245)

        fm = QFontMetrics(self._font)
        tw = max((fm.horizontalAdvance(s) for s in lines), default=10)
        lh = fm.height()
        bw = tw + 2 * self._PAD
        bh = lh * len(lines) + 2 * self._PAD
        hw, hh = host
        tipx, tipy = tip

        W, H = int(bw), int(bh + self._TAIL)
        self._below = (tipy - self._TAIL - bh) < 4  # flip below if no room above
        if self._below:
            top = tipy + self._TAIL
            self._bubble = QRectF(0, self._TAIL, bw, bh)
        else:
            top = tipy - self._TAIL - bh
            self._bubble = QRectF(0, 0, bw, bh)
        left = max(4, min(int(tipx - 0.25 * bw), hw - W - 4))
        top = max(4, min(int(top), hh - H - 4))
        # tail tip x in local coords, clamped so its base stays on the bubble
        lo = self._RADIUS + self._TAILW / 2
        hi = bw - self._RADIUS - self._TAILW / 2
        self._tipx = max(lo, min(tipx - left, hi))

        self.setGeometry(left, top, W, H)
        self.update()
        self.show()
        self.raise_()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(self._bubble, self._RADIUS, self._RADIUS)
        if self._below:
            apex, base_y = QPointF(self._tipx, 0.0), float(self._TAIL)
        else:
            apex, base_y = QPointF(self._tipx, float(self.height())), self._bubble.bottom()
        path.addPolygon(QPolygonF([
            apex,
            QPointF(self._tipx - self._TAILW / 2, base_y),
            QPointF(self._tipx + self._TAILW / 2, base_y),
        ]))
        p.setPen(QPen(self._fill.darker(120), 1))
        p.setBrush(QBrush(self._fill))
        p.drawPath(path.simplified())

        p.setPen(self._text)
        p.setFont(self._font)
        fm = QFontMetrics(self._font)
        x = int(self._bubble.left()) + self._PAD
        y = int(self._bubble.top()) + self._PAD + fm.ascent()
        for line in self._lines:
            p.drawText(x, y, line)
            y += fm.height()
        p.end()


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
        self.row_filter: list[str] = []  # snapshot of the data filter at creation

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
        self._tooltip: PlotTooltip | None = None

        # Marker sizing / zoom-adaptive state.
        self._base_size = _DEFAULT_MARKER_PX   # slider-driven base px
        self._applied_size: float | None = None  # last px set on the scatter
        self._fit_width: float | None = None   # visible data width at fit (2D)
        self._last_pos = None                   # drawn positions (for re-sizing)
        self._last_colors = None

        # Panel-driven appearance.
        self._symbol = "disc"
        self._opacity = 1.0                     # 0..1 multiplier on marker alpha
        self._full_range: tuple | None = None   # colour column extent, for Min/Max

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
                    axis_color=_AXIS_LINE, tick_color=_AXIS_TICK,
                    text_color=_AXIS_TEXT,
                )
                self._yaxis.width_max = 62
                grid.add_widget(self._yaxis, row=0, col=0)
                self._xaxis = scene.AxisWidget(
                    orientation="bottom", axis_label=self.spec.x,
                    axis_font_size=9, tick_label_margin=12,
                    axis_color=_AXIS_LINE, tick_color=_AXIS_TICK,
                    text_color=_AXIS_TEXT,
                )
                self._xaxis.height_max = 42
                grid.add_widget(self._xaxis, row=1, col=1)
                self._yaxis.link_view(view)
                self._xaxis.link_view(view)
                # Match the axis strips to the canvas so there's no white frame.
                self._xaxis.bgcolor = _BG
                self._yaxis.bgcolor = _BG
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
        self._full_range = data.full_range
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
            # orientation="left": axis label sits to the LEFT of the bar, clim
            # numbers at the ends — and nothing runs off the right edge.
            self._cbar = scene.ColorBarWidget(
                cmap=cm, orientation="left", label=str(name),
                clim=(_sig(lo), _sig(hi)), border_width=1,
                border_color="#888888",
            )
            self._cbar.width_max = 120  # room for label + 4-sig numbers, no clip
            self._cbar.bgcolor = _BG
            self._grid.add_widget(self._cbar, row=0, col=self._cbar_col)
        else:
            self._cbar.cmap = cm
            self._cbar.clim = (_sig(lo), _sig(hi))
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
        colors = self._last_colors
        if self._opacity < 1.0 and colors is not None:
            colors = colors.copy()
            colors[:, 3] = colors[:, 3] * self._opacity
        # antialias=0: hard-edged discs tile into solid colour under heavy
        # overlap instead of each blending a semi-transparent rim toward the
        # light background (the zoomed-out "whitening").
        self._scatter.set_data(self._last_pos, face_color=colors,
                               size=px, edge_width=0, edge_color=None,
                               symbol=self._symbol)
        self._scatter.antialias = 0
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

    # -- panel-driven appearance ---------------------------------------
    def set_marker_symbol(self, symbol: str) -> None:
        self._symbol = symbol or "disc"
        self._set_scatter(self._effective_size())

    def set_opacity(self, pct: int) -> None:
        self._opacity = max(0.0, min(1.0, pct / 100.0))
        self._set_scatter(self._effective_size())

    def set_colormap(self, name: str) -> None:
        self.cmap = name
        self._render()  # recompute colours + colourbar; keeps current crange

    def set_scale(self, label: str) -> None:
        self.scale = "log" if str(label).lower().startswith("log") else "linear"
        self._render()

    def _range_from_pct(self, p_lo: float, p_hi: float) -> tuple | None:
        if not self._full_range:
            return None
        fmin, fmax = self._full_range
        span = (fmax - fmin) or 1.0
        lo = fmin + (p_lo / 100.0) * span
        hi = fmin + (p_hi / 100.0) * span
        if hi < lo:
            lo, hi = hi, lo
        return (lo, hi)

    def set_color_min(self, pct: int) -> None:
        if not self._full_range:
            return
        _, cur_hi = self.crange or self._full_range
        fmin, fmax = self._full_range
        p_hi = 100.0 * (cur_hi - fmin) / ((fmax - fmin) or 1.0)
        self.crange = self._range_from_pct(pct, p_hi)
        self._render()

    def set_color_max(self, pct: int) -> None:
        if not self._full_range:
            return
        cur_lo, _ = self.crange or self._full_range
        fmin, fmax = self._full_range
        p_lo = 100.0 * (cur_lo - fmin) / ((fmax - fmin) or 1.0)
        self.crange = self._range_from_pct(p_lo, pct)
        self._render()

    def panel_state(self) -> dict:
        """Current appearance, for syncing the side panel to this plot."""
        has_color = self._full_range is not None
        cmin = cmax = None
        if has_color and self.crange is not None:
            fmin, fmax = self._full_range
            span = (fmax - fmin) or 1.0
            cmin = int(round(100.0 * (self.crange[0] - fmin) / span))
            cmax = int(round(100.0 * (self.crange[1] - fmin) / span))
        return {
            "size": self._base_size,
            "symbol": self._symbol,
            "opacity": int(round(self._opacity * 100)),
            "cmap": self.cmap,
            "scale": "Log" if self.scale == "log" else "Linear",
            "has_color": has_color,
            "cmin": cmin if cmin is not None else 0,
            "cmax": cmax if cmax is not None else 100,
        }

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
            self._show_tooltip(int(i), float(px), float(py))
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

    def _show_tooltip(self, i: int, tipx: float, tipy: float) -> None:
        text = self._hover_text(i)
        if not text or self._canvas is None:
            self._hide_tooltip()
            return
        if self._tooltip is None:
            self._tooltip = PlotTooltip(self._canvas.native)
        rgba = (0.2, 0.22, 0.26, 1.0)
        if self._last_colors is not None and 0 <= i < len(self._last_colors):
            rgba = self._last_colors[i]
        native = self._canvas.native
        self._tooltip.show_at((tipx, tipy), text.split("\n"), rgba,
                              (native.width(), native.height()))

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
