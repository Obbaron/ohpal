"""Plot tab — a dumb VisPy scatter bound to the shared result.

Holds a PlotSpec (which columns map to X/Y/Z/colour) and renders whatever
dataframe it's handed. The window re-feeds it the shared result whenever the
span or data changes; the tab never queries or assumes columns.

Decorations:
  * 2D → ticked AxisWidgets (column names as titles) + optional gridlines.
  * 3D → a wireframe bounding box + coloured axis-name labels at the box edges.
  * numeric colour → a ColorBarWidget; the toolbar toggles show/hide each.

Editable elements: the title, axes, 3D axis labels, category labels and the
colour bar can be clicked to select (an outline marks the selection) and
double-clicked to edit in the side panel. What each exposes is described in
``plot_elements``; this tab owns the live objects and applies a style to them.

VisPy is imported lazily and guarded: without it (or an OpenGL context) the tab
shows a labelled placeholder. Render arrays are released on close.
"""

from __future__ import annotations

import numpy as np
from PyQt6.QtCore import Qt, QTimer, QPointF, QRectF, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from . import plot_elements as pe
from . import plotdata
from .plotdata import DEFAULT_COLORMAP, colormap_stops
from .plotspec import PlotSpec

_BG = "#e5ecf6"  # soft blue-grey (Plotly-style) so sparse points still read
# Axis label colours (x, y, z) for the 3D decorations.
_AXIS_RGB = ((0.80, 0.12, 0.12, 1), (0.10, 0.55, 0.12, 1), (0.12, 0.30, 0.85, 1))

# Marker sizing. Base is the on-screen px at/below the fit zoom; when zoomed out
# past the fit the size grows (×FIT→×MAX) so sparse struts fill in, easing back
# to base as you zoom in. 2D only — 3D keeps a fixed size.
_DEFAULT_MARKER_PX = 3
_SIZE_FIT_MULT = 1.6
_SIZE_MAX_MULT = 3.0

# Axis decoration colours: the domain line blends into the bg, ticks/labels
# stay faintly legible.
_AXIS_LINE = _BG
_AXIS_TICK = "#8a94a6"
_AXIS_TEXT = "#5a6472"
_TITLE_TEXT = "#2a2f3a"   # plot title: darker than the axis text

# Editable elements. Chrome sizes below are the built-in look's; a bigger font
# grows its strip by the difference so text is never clipped.
_AXIS3D_KEYS = ("xaxis3d", "yaxis3d", "zaxis3d")
_TITLE_H, _XAXIS_H, _YAXIS_W = 28, 42, 62      # px, at the default font sizes
_AXIS_LABEL_MARGIN = 35                         # VisPy's default, px
_CBAR_LABEL_W, _CBAR_W = 18, 74
_CLICK_SLOP_PX = 4        # press→release travel that still counts as a click


def _style_text(tv, style: dict, prefix: str = "") -> None:
    """Apply a style's font / size / colour to a VisPy text visual, live."""
    face = pe.face(style.get(prefix + "font"))
    bold = bool(style.get(prefix + "bold", False))
    italic = bool(style.get(prefix + "italic", False))
    if (tv.face, bool(tv.bold), bool(tv.italic)) != (face, bold, italic):
        tv._face, tv._bold, tv._italic = face, bold, italic
        tv._update_font()
        tv.text = tv.text  # glyph vertices belong to a font: rebuild them
    size = float(style.get(prefix + "size", tv.font_size))
    if float(tv.font_size) != size:
        tv.font_size = size
    tv.color = style.get(prefix + "color", "#000000")


class _Highlight(QWidget):
    """Outline around the selected element. A Qt overlay on the canvas, so it
    is never part of a saved image."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.hide()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        accent = self.palette().highlight().color()
        fill = QColor(accent)
        fill.setAlpha(26)
        p.setPen(QPen(accent, 1.5))
        p.setBrush(QBrush(fill))
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.drawRoundedRect(r, 4, 4)
        p.end()


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

    # Emitted (debounced) when the Layer Viewer's scrub slider settles on a
    # layer; the window re-queries that layer and feeds it back.
    layerChanged = pyqtSignal(int)
    # Emitted when the on-plot title is renamed; the window updates the tab.
    titleChanged = pyqtSignal(str)
    # Editable elements: a click selects one ("" = selection cleared), a
    # double-click asks for its editor (the side panel).
    elementSelected = pyqtSignal(str)
    elementActivated = pyqtSignal(str)

    def __init__(self, spec: PlotSpec, span=None, title: str | None = None,
                 layers=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("tabkind", "plot")
        PlotTab._counter += 1
        self.spec = spec
        self.span = span or ("all", None, None)
        self.title = title or f"{spec.kind} {PlotTab._counter}"
        self.row_filter: list[str] = []  # snapshot of the data filter at creation
        # A self-contained plot (docked back from a floating window) carries its
        # own frozen context {store, build_name, derivations, removed,
        # row_filter}; a session-linked plot leaves this None and follows the
        # live session.
        self.context = None
        self._renames: dict = {}  # original -> display, for the hover extras
        self._layers = list(layers or [])  # Layer Viewer: the scrub range
        self._current_layer = self.span[1]  # ("single", L, L) for a Layer Viewer

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
        self._show_title = True

        self._canvas = None
        self._view = None
        self._scatter = None
        self._grid = None
        self._cbar_col = 2
        self._cbar_label_col = None  # thin column holding the colourbar's name
        self._xaxis = self._yaxis = None
        self._gridlines = None  # 2D screen-aligned gridlines
        self._floor = None      # 3D grid on the X-Y plane
        self._cbar = None
        self._cbar_label = None  # the signal name, left of the bar (no overlap)
        self._bbox = None
        self._axis_labels: list = []
        self._status: QLabel | None = None

        # Bar plot visuals (a quad mesh + a baseline x-axis + category labels).
        self._bars = None
        self._bar_axis = None   # horizontal baseline (the x axis) under the bars
        self._bar_labels: list = []
        self._bar_data = None

        # Contour visuals (a gridded image + the measured-point overlay).
        self._contour_img = None
        self._contour_pts = None
        self._contour_data = None

        # Hover tooltip: the rows behind the drawn points + a floating label
        # near the cursor. 2D picks via a data-space KDTree; 3D projects the
        # points to the screen each move (the turntable camera rotates).
        self._hover_tree = None
        self._hover_xy = None
        self._hover_pos = None  # 3D: the drawn (N, 3) positions, screen-projected
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

        # Editable elements: one resolved style per element (the default for
        # new plots, then this plot's edits), the selection and its outline.
        self._el_style: dict[str, dict] = {
            k: pe.default_style(k) for k in pe.keys_for(spec)}
        self._selected: str | None = None
        self._hl: _Highlight | None = None
        self._press_pos = None       # left-button press, to tell click from drag
        self._rect_cache: dict = {}  # element rects, valid for one frame
        self._cbar_auto = ""         # the colour bar's automatic label
        self._hand = False           # pointing-hand cursor shown?
        self._fit_pending = False    # a Y-strip fit is queued for after a frame

        self._title_label = None  # a VisPy Label inside the canvas
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._body = self._build_canvas()
        self._lay.addWidget(self._body)
        self._slider = None
        self._scrub_timer = None
        if spec.is_layer_viewer:
            self._build_scrubber()

    @property
    def span_label(self) -> str:
        mode, lo, hi = self.span
        if mode == "all":
            return "all layers"
        return f"layer {lo}" if lo == hi else f"layers {lo}–{hi}"

    def set_loading(self, text: str) -> None:
        self._show_overlay(text)

    # -- layer scrubber (Layer Viewer only) ----------------------------
    def _build_scrubber(self) -> None:
        """A slider under the plot that scrubs through layers; each settle
        re-queries that layer (debounced) via ``layerChanged``."""
        bar = QHBoxLayout()
        bar.setContentsMargins(12, 2, 14, 6)
        bar.setSpacing(8)
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, max(0, len(self._layers) - 1))
        self._layer_label = QLabel("")
        self._layer_label.setMinimumWidth(78)
        start = (self._layers.index(self._current_layer)
                 if self._current_layer in self._layers else 0)
        self._slider.setValue(start)
        self._update_layer_label(start)
        self._slider.valueChanged.connect(self._on_scrub)
        bar.addWidget(QLabel("Layer"))
        bar.addWidget(self._slider, 1)
        bar.addWidget(self._layer_label)
        holder = QWidget()
        holder.setLayout(bar)
        self._lay.addWidget(holder)
        # Debounce: re-query once the slider settles, not on every tick.
        self._scrub_timer = QTimer(self)
        self._scrub_timer.setSingleShot(True)
        self._scrub_timer.setInterval(80)
        self._scrub_timer.timeout.connect(self._emit_scrub)

    def _on_scrub(self, idx: int) -> None:
        self._update_layer_label(idx)  # label tracks the handle immediately
        self._scrub_timer.start()      # fires 80 ms after the last move

    def _emit_scrub(self) -> None:
        i = self._slider.value()
        if 0 <= i < len(self._layers):
            self._current_layer = self._layers[i]
            self.layerChanged.emit(self._current_layer)

    def _update_layer_label(self, idx: int) -> None:
        if 0 <= idx < len(self._layers):
            self._layer_label.setText(f"Layer {self._layers[idx]}")

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
            pe.ensure_fonts()
            canvas = scene.SceneCanvas(keys="interactive", bgcolor=_BG, show=False)
            grid = canvas.central_widget.add_grid(margin=6)
            self._grid = grid
            # Title strip inside the canvas (so it's part of screenshots) at
            # row 0, over the plot's own column — col 0 for 3D, col 1 for 2D
            # (right of the y-axis). Spanning into the colourbar/empty columns
            # would invent a stretchy phantom column that steals half the width.
            self._title_label = scene.Label(
                self.title, color=_TITLE_TEXT, font_size=13)
            self._title_label.height_max = _TITLE_H
            grid.add_widget(self._title_label, row=0,
                            col=0 if self.spec.is_3d else 1)
            self._title_label.visible = self._show_title
            if self.spec.is_3d:
                # No left axis column in 3D — an empty grid column would take an
                # equal stretch and shove the view into the right half. View at
                # col 0, colourbar at col 1.
                view = grid.add_view(row=1, col=0)
                view.camera = scene.cameras.TurntableCamera(fov=45)
                self._cbar_col = 1
            else:
                view = grid.add_view(row=1, col=1)
                # aspect=1 → one X unit == one Y unit, so parts aren't skewed.
                view.camera = scene.cameras.PanZoomCamera(aspect=1)
                self._cbar_col = 2
                self._yaxis = scene.AxisWidget(
                    orientation="left", axis_label=self.spec.y,
                    axis_font_size=9, tick_label_margin=12,
                    axis_color=_AXIS_LINE, tick_color=_AXIS_TICK,
                    text_color=_AXIS_TEXT,
                )
                self._yaxis.width_max = _YAXIS_W
                grid.add_widget(self._yaxis, row=1, col=0)
                self._xaxis = scene.AxisWidget(
                    orientation="bottom", axis_label=self.spec.x,
                    axis_font_size=9, tick_label_margin=12,
                    axis_color=_AXIS_LINE, tick_color=_AXIS_TICK,
                    text_color=_AXIS_TEXT,
                )
                self._xaxis.height_max = _XAXIS_H
                grid.add_widget(self._xaxis, row=2, col=1)
                self._yaxis.link_view(view)
                self._xaxis.link_view(view)
                # Match the axis strips to the canvas so there's no white frame.
                self._xaxis.bgcolor = _BG
                self._yaxis.bgcolor = _BG
                self._gridlines = scene.visuals.GridLines(
                    color=(0, 0, 0, 0.12), parent=view.scene
                )
                self._gridlines.visible = self._show_grid
            # The colourbar's name lives in its own thin column just left of the
            # bar (vertical text), so it sits in whitespace and never overlaps
            # the bar. The bar itself then moves one column to the right.
            self._cbar_label_col = self._cbar_col
            self._cbar_col += 1
            self._cbar_label = scene.Label(
                "", rotation=-90, color=_AXIS_TEXT, font_size=9)
            self._cbar_label.width_max = _CBAR_LABEL_W
            grid.add_widget(self._cbar_label, row=1, col=self._cbar_label_col)
            self._cbar_label.visible = False
            self._scatter = scene.visuals.Markers()
            view.add(self._scatter)
            self._canvas, self._view = canvas, view
            canvas.events.mouse_move.connect(self._on_mouse_move)
            canvas.events.mouse_wheel.connect(self._on_wheel)
            canvas.events.mouse_double_click.connect(self._on_double_click)
            canvas.events.mouse_press.connect(self._on_mouse_press)
            canvas.events.mouse_release.connect(self._on_mouse_release)
            canvas.events.draw.connect(self._on_draw)
            self._apply_elements()  # saved defaults onto the fresh chrome
            return canvas.native
        except Exception as exc:  # noqa: BLE001 - GL context failure -> placeholder
            return _placeholder(f"Could not start the canvas:\n{exc}")

    # -- data ----------------------------------------------------------
    def set_renames(self, renames) -> None:
        """Hand the current rename map (original -> display), used to resolve the
        hover tooltip's part_id / layer extras to their renamed names."""
        self._renames = dict(renames or {})

    def set_dataframe(self, df) -> None:
        """(Re)render with a new dataframe, keeping the same spec."""
        self._df = df
        self._render()

    def _render(self) -> None:
        if self._df is None or self._scatter is None:
            return
        if self.spec.is_contour:
            self._render_contour()
            return
        if self.spec.is_bar or self.spec.is_hist or self.spec.is_cov:
            self._render_bars()
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
        self._apply_elements()
        self._apply_visibility()
        if self._view is not None and first:
            # Defer the fit so the grid (incl. the just-added colourbar) has
            # settled and the view has its real size before framing.
            QTimer.singleShot(0, self.reset_view)

    # -- bar rendering -------------------------------------------------
    def _render_bars(self) -> None:
        from vispy import scene

        if self.spec.is_hist:
            builder = plotdata.build_histogram
        elif self.spec.is_cov:
            builder = plotdata.build_cov
        else:
            builder = plotdata.build_bars
        try:
            data = builder(self._df, self.spec, cmap=self.cmap,
                           scale=self.scale, crange=self.crange)
        except KeyError as exc:
            self._show_overlay(str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            self._show_overlay(f"Could not plot: {exc}")
            return
        if data.n == 0:
            self._show_overlay("Nothing to plot for this selection.")
            return
        self._clear_overlay()
        if self._scatter is not None and self._scatter.parent is not None:
            # Remove the (data-less) scatter from the scene: set_range walks
            # every visual's bounds, and an un-fed Markers crashes on None data.
            self._scatter.parent = None
            self._scatter.visible = False
        # Bars/histograms are not spatial — free the x/y aspect so a near-flat
        # value range can't collapse the (aspect-locked) camera into NaNs.
        try:
            self._view.camera.aspect = None
        except Exception:  # noqa: BLE001
            pass
        if self.crange is None:
            self.crange = data.crange
        self._full_range = data.full_range
        self._bar_data = data
        # The left axis measures the bar height (count / CoV / value), not the
        # raw signal column — _auto_text labels it from what the bars are.

        n = data.n
        w = data.width or 0.8
        heights = np.where(np.isfinite(data.heights), data.heights, 0.0)
        verts = np.empty((4 * n, 3), "float32")
        faces = np.empty((2 * n, 3), "uint32")
        vcol = np.empty((4 * n, 4), "float32")
        for i in range(n):
            h = float(heights[i])
            c = float(data.centers[i])
            x0, x1 = c - w / 2, c + w / 2
            b = 4 * i
            verts[b:b + 4] = [[x0, 0, 0], [x1, 0, 0], [x1, h, 0], [x0, h, 0]]
            faces[2 * i:2 * i + 2] = [[b, b + 1, b + 2], [b, b + 2, b + 3]]
            vcol[b:b + 4] = data.colors[i]
        if self._bars is None:
            self._bars = scene.visuals.Mesh(
                vertices=verts, faces=faces, vertex_colors=vcol,
                parent=self._view.scene)
        else:
            self._bars.set_data(vertices=verts, faces=faces, vertex_colors=vcol)

        for t in self._bar_labels:
            t.parent = None
        self._bar_labels = []
        hvals = data.heights[np.isfinite(data.heights)]
        ymin = min(0.0, float(hvals.min()) if hvals.size else 0.0)
        ymax = max(0.0, float(hvals.max()) if hvals.size else 1.0)
        if ymax <= ymin:  # flat/degenerate heights → give the view a real span
            ymax = ymin + 1.0
        # The x axis is a rule just below the bars' baseline (ymin); category
        # labels drop a further gap below that rule so they read as tick labels
        # rather than text sitting inside the bars.
        gap = 0.045 * (ymax - ymin)
        axis_y = ymin - 0.35 * gap
        label_y = ymin - gap
        if data.categorical and data.labels:  # category text under the x axis
            # The labels hang from just under the rule, so a bigger font grows
            # downwards, away from the bars. (VisPy's "bottom" anchor is the
            # text's top edge in a y-up view.)
            hang_y = ymin - 0.45 * gap
            for i, label in enumerate(data.labels):
                t = scene.visuals.Text(
                    label, pos=(float(data.centers[i]), hang_y), color=_AXIS_TEXT,
                    anchor_x="center", anchor_y="bottom", font_size=9,
                    parent=self._view.scene)
                self._bar_labels.append(t)

        clo, chi = float(data.crange[0]), float(data.crange[1])
        if chi <= clo:  # flat values → a readable colourbar still needs a span
            chi = clo + 1.0
        self._set_colorbar(clo, chi, data.value_name)
        xlo = float(data.centers.min()) - w / 2
        xhi = float(data.centers.max()) + w / 2
        # A visible rule is the category x-axis; the region labels (at y=label_y)
        # then sit just below this line. Histograms keep the numeric x axis
        # (the AxisWidget), so the rule is category-bar only.
        if data.categorical:
            axis_pos = np.array([[xlo, axis_y], [xhi, axis_y]], "float32")
            if self._bar_axis is None:
                self._bar_axis = scene.visuals.Line(
                    pos=axis_pos, color=_AXIS_TICK, width=1.0,
                    parent=self._view.scene)
            else:
                self._bar_axis.set_data(pos=axis_pos)
                if self._bar_axis.parent is None:
                    self._bar_axis.parent = self._view.scene
            self._bar_axis.visible = self._show_axes
            y_lo = label_y  # frame the labels in (reset_view adds glyph room)
        elif self._bar_axis is not None:  # histogram → no baseline rule
            self._bar_axis.parent = None
            y_lo = ymin
        else:
            y_lo = ymin
        self._data_bounds = (np.array([xlo, y_lo], "float32"),
                             np.array([xhi, ymax], "float32"))
        self._apply_elements()
        self._apply_visibility()
        first = not self._rendered_once
        self._rendered_once = True
        if self._view is not None and first:
            QTimer.singleShot(0, self.reset_view)

    # -- contour rendering ---------------------------------------------
    def _render_contour(self) -> None:
        from vispy import scene
        from vispy.visuals.transforms import STTransform

        try:
            data = plotdata.build_contour(self._df, self.spec, cmap=self.cmap,
                                          scale=self.scale, crange=self.crange)
        except KeyError as exc:
            self._show_overlay(str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            self._show_overlay(f"Could not plot: {exc}")
            return
        if data.n == 0:
            self._show_overlay("Nothing to plot for this selection.")
            return
        self._clear_overlay()
        # Drop the (data-less) scatter from the scene so set_range can't crash.
        if self._scatter is not None and self._scatter.parent is not None:
            self._scatter.parent = None
            self._scatter.visible = False
        try:
            self._view.camera.aspect = None  # free aspect — param axes differ
        except Exception:  # noqa: BLE001
            pass
        if self.crange is None:
            self.crange = data.crange
        self._full_range = data.full_range
        self._contour_data = data

        # Colour the gridded field through the colormap; empty cells go clear.
        lo, hi = float(data.crange[0]), float(data.crange[1])
        span = (hi - lo) or 1.0
        z = data.z
        t = np.clip((z - lo) / span, 0.0, 1.0)
        rgba = plotdata._apply_cmap(
            np.nan_to_num(t).ravel(), self.cmap).reshape(z.shape[0], z.shape[1], 4)
        rgba[~np.isfinite(z)] = 0.0  # transparent gaps
        rgba = rgba.astype("float32")

        xs, ys = data.x_values, data.y_values
        nx, ny = len(xs), len(ys)
        xmin, xmax = float(xs.min()), float(xs.max())
        ymin, ymax = float(ys.min()), float(ys.max())
        dx = (xmax - xmin) / (nx - 1) if nx > 1 else 1.0
        dy = (ymax - ymin) / (ny - 1) if ny > 1 else 1.0
        x0, y0 = xmin - dx / 2, ymin - dy / 2

        if self._contour_img is None:
            self._contour_img = scene.visuals.Image(
                rgba, parent=self._view.scene, interpolation="nearest")
        else:
            self._contour_img.set_data(rgba)
            if self._contour_img.parent is None:
                self._contour_img.parent = self._view.scene
        # Texel (col,row) centre -> data (x,y); row 0 = smallest y (y up).
        self._contour_img.transform = STTransform(
            scale=(dx, dy), translate=(x0, y0))
        self._contour_img.order = 0
        self._contour_img.visible = True

        # Overlay the measured (x, y) samples, drawn above the field.
        if data.show_points and data.points.shape[0]:
            if self._contour_pts is None:
                self._contour_pts = scene.visuals.Markers(parent=self._view.scene)
                # Ignore depth so the overlay always wins over the opaque field.
                self._contour_pts.set_gl_state("translucent", depth_test=False)
            elif self._contour_pts.parent is None:
                self._contour_pts.parent = self._view.scene
            self._contour_pts.set_data(
                data.points, face_color=(1, 1, 1, 0.9),
                edge_color=(0, 0, 0, 0.7), edge_width=1, size=6, symbol="disc")
            self._contour_pts.antialias = 1
            self._contour_pts.order = 1   # draw on top of the image
            self._contour_pts.visible = True
        elif self._contour_pts is not None:
            self._contour_pts.visible = False

        clo, chi = lo, hi
        if chi <= clo:  # flat field → a readable colourbar still needs a span
            chi = clo + 1.0
        self._set_colorbar(clo, chi, data.value_name)
        self._data_bounds = (np.array([x0, y0], "float32"),
                             np.array([xmax + dx / 2, ymax + dy / 2], "float32"))
        self._apply_elements()
        self._apply_visibility()
        first = not self._rendered_once
        self._rendered_once = True
        if self._view is not None and first:
            QTimer.singleShot(0, self.reset_view)

    def _bar_hover(self, event) -> None:
        if (self._bar_data is None or self._bars is None
                or getattr(event, "pos", None) is None):
            return
        if getattr(event, "buttons", None):
            self._hide_tooltip()
            return
        try:
            dx, dy = self._bars.get_transform("canvas", "visual").map(event.pos)[:2]
            data = self._bar_data
            w = data.width or 0.8
            i = int(np.argmin(np.abs(data.centers - dx)))
            if not (0 <= i < data.n) or abs(dx - float(data.centers[i])) > w / 2:
                self._hide_tooltip()
                return
            h = float(data.heights[i]) if np.isfinite(data.heights[i]) else 0.0
            lo, hi = (0.0, h) if h >= 0 else (h, 0.0)
            if not (lo - 1e-6 <= dy <= hi + 1e-6):
                self._hide_tooltip()
                return
            px, py = self._bars.get_transform("visual", "canvas").map(
                [float(data.centers[i]), h])[:2]
            if data.labels is not None:          # bar: show the category
                head = f"{data.x_name}: {data.labels[i]}"
            else:                                # histogram: show the bin range
                head = (f"{data.x_name}: {_fmt(data.centers[i] - w / 2)}"
                        f"–{_fmt(data.centers[i] + w / 2)}")
            text = f"{head}\n{data.value_name}: {_fmt(h)}"
            if self._tooltip is None:
                self._tooltip = PlotTooltip(self._canvas.native)
            native = self._canvas.native
            self._tooltip.show_at((px, py), text.split("\n"), data.colors[i],
                                  (native.width(), native.height()))
        except Exception:  # noqa: BLE001
            self._hide_tooltip()

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
            if self._cbar_label is not None:
                self._cbar_label.visible = False

    def _set_colorbar(self, lo, hi, name) -> None:
        from vispy import scene
        from vispy.color import Colormap

        cm = Colormap(colormap_stops(self.cmap))
        if self._cbar is None:
            # No built-in label: the name is a separate vertical Label in the
            # column to the left (see _build_canvas). The bar carries only the
            # clim numbers at its ends, so it needs much less width.
            self._cbar = scene.ColorBarWidget(
                cmap=cm, orientation="left", label="",
                clim=(_sig(lo), _sig(hi)), border_width=1,
                border_color="#888888",
            )
            self._cbar.width_max = _CBAR_W  # bar + end numbers (name: own col)
            self._cbar.bgcolor = _BG
            self._grid.add_widget(self._cbar, row=1, col=self._cbar_col)
        else:
            self._cbar.cmap = cm
            self._cbar.clim = (_sig(lo), _sig(hi))
        self._cbar_auto = str(name)
        if self._cbar_label is not None:
            self._cbar_label.visible = self._show_legend
        self._cbar.visible = self._show_legend
        self._apply_element("cbar")  # label text + fonts (a new bar included)

    def _apply_visibility(self) -> None:
        if self._yaxis is not None:
            self._yaxis.visible = self._show_axes
        if self._xaxis is not None:
            # Category bars use text labels, not the numeric x axis; histograms
            # keep the numeric x axis.
            self._xaxis.visible = (
                self._show_axes and not (self.spec.is_bar or self.spec.is_cov))
        if self._gridlines is not None:
            self._gridlines.visible = self._show_grid
        if self._floor is not None:
            self._floor.visible = self._show_grid
        if self._bbox is not None:
            self._bbox.visible = self._show_bbox
        for t in self._axis_labels:
            t.visible = self._show_axes
        if self._bar_axis is not None:
            self._bar_axis.visible = self._show_axes
        for t in self._bar_labels:
            t.visible = self._show_axes
        if self._cbar is not None:
            self._cbar.visible = self._show_legend
        if self._cbar_label is not None:
            self._cbar_label.visible = self._show_legend and self._cbar is not None
        self._elements_changed()  # a hidden element can't stay outlined

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

    def set_title_visible(self, on: bool) -> None:
        self._show_title = on
        if self._title_label is not None:
            self._title_label.visible = on
            # Off reclaims the strip's space.
            self._title_label.height_max = self._title_height() if on else 0
            self._relayout()
            if self._canvas is not None:
                self._canvas.update()
        self._elements_changed()

    def _set_title(self, name: str) -> None:
        name = name.strip()
        if not name:
            return
        self.title = name
        if self._title_label is not None:
            self._title_label.text = name
        self.titleChanged.emit(name)

    # -- editable elements ----------------------------------------------
    def _px(self, pt: float) -> float:
        """Font points → canvas pixels."""
        dpi = getattr(self._canvas, "dpi", None) or 96.0
        return float(pt) * float(dpi) / 72.0

    def _title_height(self) -> float:
        size = self._el_style["title"]["size"]
        return max(18.0, _TITLE_H + 1.5 * (self._px(size) - self._px(13)))

    def _auto_text(self, key: str) -> str:
        """An element's automatic text — what it shows with no override."""
        if key in ("xaxis", "xaxis3d"):
            return str(self.spec.x or "")
        if key == "yaxis":
            if self._bar_data is not None:  # bars measure count / CoV / value
                return str(self._bar_data.value_name)
            return str(self.spec.y or "")
        if key == "yaxis3d":
            return str(self.spec.y or "")
        if key == "zaxis3d":
            return str(self.spec.z or "")
        if key == "cbar":
            return self._cbar_auto
        return ""

    def element_keys(self) -> list[str]:
        """The editable elements on screen right now."""
        return [k for k in self._el_style if self._element_present(k)]

    def _element_present(self, key: str) -> bool:
        if key == "title":
            return self._title_label is not None and self._show_title
        if key == "xaxis":
            return self._xaxis is not None and bool(self._xaxis.visible)
        if key == "yaxis":
            return self._yaxis is not None and bool(self._yaxis.visible)
        if key in _AXIS3D_KEYS:
            return (self._show_axes
                    and _AXIS3D_KEYS.index(key) < len(self._axis_labels))
        if key == "categories":
            return self._show_axes and bool(self._bar_labels)
        if key == "cbar":
            return self._cbar is not None and bool(self._cbar.visible)
        return False

    def element_values(self, key: str) -> dict:
        """The element's current style, for the editor."""
        vals = dict(self._el_style.get(key, {}))
        if key == "title":
            vals["text"] = self.title
        return vals

    def element_auto_text(self, key: str) -> str:
        return self._auto_text(key)

    def selected_element(self) -> str | None:
        return self._selected

    def set_element(self, key: str, name: str, value) -> None:
        """Change one property of an element; the plot updates in place."""
        style = self._el_style.get(key)
        if style is None:
            return
        if key == "title" and name == "text":
            self._set_title(str(value))  # the plot's name (and its tab's)
            self._elements_changed()
            return
        if name not in style:
            return
        style[name] = value
        self._apply_element(key)
        self._elements_changed()

    def reset_element(self, key: str, builtin: bool = False) -> None:
        """Back to the default for new plots (or the built-in look). The text
        is kept — only the styling resets."""
        if key not in self._el_style:
            return
        fresh = pe.builtin_style(key) if builtin else pe.default_style(key)
        if "text" in fresh:
            fresh["text"] = self._el_style[key].get("text", "")
        self._el_style[key] = fresh
        self._apply_element(key)
        self._elements_changed()

    def save_element_default(self, key: str) -> None:
        """Make this element's styling the default for new plots."""
        if key in self._el_style:
            pe.save_default(key, self._el_style[key])

    def _apply_elements(self) -> None:
        for key in self._el_style:
            self._apply_element(key)

    def _apply_element(self, key: str) -> None:
        """Push an element's style onto its live VisPy objects."""
        st = self._el_style.get(key)
        if st is None or self._grid is None:
            return
        try:
            if key == "title":
                if self._title_label is not None:
                    _style_text(self._title_label._text_visual, st)
                    self._title_label.height_max = (
                        self._title_height() if self._show_title else 0)
            elif key in ("xaxis", "yaxis"):
                self._apply_axis(key, st)
            elif key in _AXIS3D_KEYS:
                i = _AXIS3D_KEYS.index(key)
                if i < len(self._axis_labels):
                    label = self._axis_labels[i]
                    label.text = st.get("text") or self._auto_text(key)
                    _style_text(label, st)
            elif key == "categories":
                for label in self._bar_labels:
                    _style_text(label, st)
            elif key == "cbar":
                if self._cbar_label is not None:
                    self._cbar_label.text = st.get("text") or self._cbar_auto
                    _style_text(self._cbar_label._text_visual, st)
                    self._cbar_label.width_max = max(12.0, _CBAR_LABEL_W + 1.3 * (
                        self._px(st["size"]) - self._px(9)))
                if self._cbar is not None:
                    for tick in self._cbar.ticks:
                        _style_text(tick, st, "num_")
                    self._cbar.width_max = max(48.0, _CBAR_W + 2.6 * (
                        self._px(st["num_size"]) - self._px(12)))
            self._relayout()
        except Exception:  # noqa: BLE001 - styling is cosmetic; never break a plot
            pass

    def _relayout(self) -> None:
        """Have the canvas grid pick up changed strip sizes (it only re-reads
        a widget's size limits when its solver is rebuilt)."""
        if self._grid is not None:
            self._grid._need_solver_recreate = True
            self._grid.update()

    def _apply_axis(self, key: str, st: dict) -> None:
        widget = self._xaxis if key == "xaxis" else self._yaxis
        if widget is None:
            return
        axis = widget.axis
        axis.axis_label = st.get("text") or self._auto_text(key)
        _style_text(axis._axis_label_vis, st)
        _style_text(axis._text, st, "tick_")
        # Bigger fonts need a deeper strip and the title pushed further out.
        d_title = self._px(st["size"]) - self._px(9)
        d_tick = self._px(st["tick_size"]) - self._px(8)
        if key == "xaxis":  # tick labels stack above the title
            axis.axis_label_margin = max(
                16.0, _AXIS_LABEL_MARGIN + d_tick + 0.5 * d_title)
            widget.height_max = max(24.0, _XAXIS_H + d_tick + 1.3 * d_title)
        else:               # tick labels sit beside the (rotated) title
            self._fit_yaxis(force=True)

    def _fit_yaxis(self, force: bool = False) -> None:
        """Size the Y strip to the tick labels on screen, so the (rotated)
        title never sits on top of them — however long the numbers get and
        whatever the two font sizes are. Grows at once, shrinks lazily, so a
        pan that flips "-9.5" to "-10" doesn't make the plot jitter."""
        self._fit_pending = False
        widget = self._yaxis
        if widget is None:
            return
        st, axis = self._el_style["yaxis"], widget.axis
        labels = axis._text.text or []
        if isinstance(labels, str):
            labels = [labels]
        tick_font = QFont(st.get("tick_font") or pe.DEFAULT_FONT)
        tick_font.setPixelSize(max(1, int(round(self._px(st["tick_size"])))))
        fm = QFontMetricsF(tick_font)
        widest = max((fm.horizontalAdvance(str(t)) for t in labels), default=0.0)
        half_title = 0.6 * self._px(st["size"])  # the rotated title's half-depth
        d_title = self._px(st["size"]) - self._px(9)
        # Measured from the tick ends: tick-label gap + label + air + half title.
        need = max(_AXIS_LABEL_MARGIN + 0.5 * d_title,
                   float(axis.tick_label_margin) + widest + 4.0 + half_title)
        cur = float(axis.axis_label_margin)
        if force or need > cur + 1.0 or need < cur - 12.0:
            axis.axis_label_margin = need
            widget.width_max = max(
                30.0, _YAXIS_W + (need - _AXIS_LABEL_MARGIN) + 0.7 * d_title)
            self._relayout()

    def _elements_changed(self) -> None:
        """An element's look or presence changed: redraw; the outline follows
        on the next frame (after the grid has re-laid out)."""
        self._rect_cache = {}
        if self._canvas is not None:
            self._canvas.update()
        QTimer.singleShot(0, self._sync_highlight)

    # geometry (canvas pixels == the native widget's pixels)
    def _widget_rect(self, widget) -> QRectF | None:
        if widget is None:
            return None
        tr = widget.transforms.get_transform("visual", "canvas")
        x0, y0 = (float(v) for v in tr.map((0, 0))[:2])
        x1, y1 = (float(v) for v in tr.map(tuple(widget.size))[:2])
        return QRectF(QPointF(min(x0, x1), min(y0, y1)),
                      QPointF(max(x0, x1), max(y0, y1)))

    def _text_box(self, text: str, st: dict, cx: float, cy: float, *,
                  rotated: bool = False, top: bool = False) -> QRectF:
        """Where a piece of text sits, from its font metrics. ``top`` anchors
        the text's top edge at ``cy`` (else it is centred there)."""
        font = QFont(st.get("font") or pe.DEFAULT_FONT)
        font.setPixelSize(max(1, int(round(self._px(st.get("size", 9))))))
        font.setBold(bool(st.get("bold", False)))
        font.setItalic(bool(st.get("italic", False)))
        fm = QFontMetricsF(font)
        w, h = max(fm.horizontalAdvance(text or " "), 12.0), fm.height()
        if rotated:
            w, h = h, w
        y = cy if top else cy - h / 2
        return QRectF(cx - w / 2, y, w, h).adjusted(-6, -3, 6, 3)

    def _scene_points(self, visual, pos) -> list[tuple[float, float]]:
        """Project scene positions to canvas pixels (skipping any behind the
        camera)."""
        pts = np.atleast_2d(np.asarray(pos, dtype="float64"))
        proj = np.atleast_2d(
            visual.get_transform("visual", "canvas").map(pts))
        out = []
        for row in proj:
            w = float(row[3]) if row.shape[0] > 3 else 1.0
            if w > 1e-6:
                out.append((float(row[0]) / w, float(row[1]) / w))
        return out

    def _element_rect(self, key: str) -> QRectF | None:
        if key in self._rect_cache:
            return self._rect_cache[key]
        rect = None
        try:
            if self._element_present(key):
                rect = self._compute_rect(key)
        except Exception:  # noqa: BLE001 - no rect → simply not clickable
            rect = None
        self._rect_cache[key] = rect
        return rect

    def _compute_rect(self, key: str) -> QRectF | None:
        st = self._el_style[key]
        if key == "title":
            strip = self._widget_rect(self._title_label)
            c = strip.center()
            return self._text_box(self.title, st, c.x(), c.y()).intersected(
                strip.adjusted(0, -4, 0, 4))
        if key == "xaxis":
            # The title hangs a little below its strip (into the canvas
            # margin), so the outline takes the title's own box in too.
            strip = self._widget_rect(self._xaxis)
            axis = self._xaxis.axis
            below = float(axis.major_tick_length) + float(axis.axis_label_margin)
            title = self._text_box(
                st.get("text") or self._auto_text(key), st,
                strip.center().x(), strip.top() + below)
            canvas = QRectF(0, 0, *(float(v) for v in self._canvas.size))
            return strip.united(title).intersected(canvas)
        if key == "yaxis":
            return self._widget_rect(self._yaxis)
        if key == "cbar":
            rect = self._widget_rect(self._cbar)
            if self._cbar_label is not None and self._cbar_label.visible:
                rect = rect.united(self._widget_rect(self._cbar_label))
            return rect
        if key in _AXIS3D_KEYS:
            label = self._axis_labels[_AXIS3D_KEYS.index(key)]
            pts = self._scene_points(label, label.pos)
            if not pts:
                return None
            text = st.get("text") or self._auto_text(key)
            return self._text_box(text, st, *pts[0])
        if key == "categories":
            rect = None
            for label in self._bar_labels:
                for x, y in self._scene_points(label, label.pos):
                    box = self._text_box(str(label.text), st, x, y, top=True)
                    rect = box if rect is None else rect.united(box)
            view = self._widget_rect(self._view)
            return rect.intersected(view) if rect is not None else None
        return None

    def _element_at(self, pos) -> str | None:
        """The element under a canvas position (None over the data)."""
        if pos is None:
            return None
        pt = QPointF(float(pos[0]), float(pos[1]))
        for key in self._el_style:
            rect = self._element_rect(key)
            if rect is not None and rect.contains(pt):
                return key
        return None

    def select_element(self, key: str | None) -> None:
        """Select an element (outlined on the plot), or clear with None."""
        key = key if key in self._el_style else None
        if key == self._selected:
            return
        self._selected = key
        self._sync_highlight()
        self.elementSelected.emit(key or "")

    def _sync_highlight(self) -> None:
        if self._canvas is None:
            return
        rect = self._element_rect(self._selected) if self._selected else None
        if rect is None or rect.isEmpty():
            if self._hl is not None:
                self._hl.hide()
            return
        if self._hl is None:
            self._hl = _Highlight(self._canvas.native)
        geo = rect.toAlignedRect()
        if self._hl.geometry() != geo:
            self._hl.setGeometry(geo)
        if not self._hl.isVisible():
            self._hl.show()
            self._hl.raise_()

    def _on_draw(self, _event) -> None:
        # A new frame: the layout / camera may have moved every element.
        self._rect_cache = {}
        if self._selected is not None:
            QTimer.singleShot(0, self._sync_highlight)
        if self._yaxis is not None and not self._fit_pending:
            self._fit_pending = True  # the tick labels may have changed
            QTimer.singleShot(0, self._fit_yaxis)

    def _on_mouse_press(self, event) -> None:
        pos = getattr(event, "pos", None)
        self._press_pos = (
            (float(pos[0]), float(pos[1]))
            if pos is not None and getattr(event, "button", None) == 1 else None)

    def _on_mouse_release(self, event) -> None:
        start, self._press_pos = self._press_pos, None
        pos = getattr(event, "pos", None)
        if start is None or pos is None or getattr(event, "button", None) != 1:
            return
        if ((pos[0] - start[0]) ** 2 + (pos[1] - start[1]) ** 2
                > _CLICK_SLOP_PX ** 2):
            return  # a drag (pan / rotate), not a click
        self.select_element(self._element_at(pos))

    def _on_double_click(self, event) -> None:
        """Double-click an element to edit it in the side panel."""
        key = self._element_at(getattr(event, "pos", None))
        if key is None:
            return
        self.select_element(key)
        self.elementActivated.emit(key)

    def _hover_cursor(self, event) -> None:
        """Pointing hand over anything that can be clicked to edit."""
        if self._canvas is None or getattr(event, "buttons", None):
            return
        over = self._element_at(getattr(event, "pos", None)) is not None
        if over != self._hand:
            self._hand = over
            if over:
                self._canvas.native.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self._canvas.native.unsetCursor()

    def reset_view(self) -> None:
        if self._view is None:
            return
        b = self._data_bounds
        if b is None:  # fall back to the whole scene
            self._view.camera.set_range(margin=0.12)
            return
        lo, hi = b  # frame the data, not the padded floor grid

        def _span(a, z):  # never a zero-width range (would NaN the transform)
            a, z = float(a), float(z)
            return (a, z) if z > a else (a - 0.5, a + 0.5)

        if self.spec.is_3d:
            self._view.camera.set_range(x=_span(lo[0], hi[0]), y=_span(lo[1], hi[1]),
                                        z=_span(lo[2], hi[2]), margin=0.12)
        else:
            self._view.camera.set_range(x=_span(lo[0], hi[0]), y=_span(lo[1], hi[1]),
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
            "title": self._show_title, "is_3d": self.spec.is_3d,
        }

    def appearance(self) -> dict:
        """Full visual state, for cloning this plot into a detached window."""
        return {
            "cmap": self.cmap, "scale": self.scale, "crange": self.crange,
            "size": self._base_size, "symbol": self._symbol,
            "opacity": self._opacity, "axes": self._show_axes,
            "grid": self._show_grid, "bbox": self._show_bbox,
            "legend": self._show_legend, "title": self._show_title,
            "title_text": self.title,
            "elements": {k: dict(v) for k, v in self._el_style.items()},
        }

    def apply_appearance(self, a: dict) -> None:
        """Adopt a saved ``appearance`` before the first render (no re-render
        here — the caller feeds data next)."""
        self.cmap = a.get("cmap", self.cmap)
        self.scale = a.get("scale", self.scale)
        self.crange = a.get("crange", self.crange)
        self._base_size = a.get("size", self._base_size)
        self._symbol = a.get("symbol", self._symbol)
        self._opacity = a.get("opacity", self._opacity)
        self._show_axes = a.get("axes", self._show_axes)
        self._show_grid = a.get("grid", self._show_grid)
        self._show_bbox = a.get("bbox", self._show_bbox)
        self._show_legend = a.get("legend", self._show_legend)
        self._show_title = a.get("title", self._show_title)
        self.title = a.get("title_text", self.title)
        for key, style in (a.get("elements") or {}).items():
            if key in self._el_style and isinstance(style, dict):
                self._el_style[key].update(style)
        if self._title_label is not None:
            self._title_label.text = self.title
            self._title_label.visible = self._show_title
        self._apply_elements()

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
        """Index the drawn points for nearest-point hover.

        2D builds a data-space KDTree (the camera only pans/zooms, so a point's
        data XY is a stable key). 3D keeps the raw (N, 3) positions and projects
        them to the screen on each move, since the turntable camera rotates.
        """
        self._hover_tree = self._hover_xy = self._hover_pos = None
        if data.rows is None or data.n_drawn == 0:
            self._hover_rows = None
            self._hide_tooltip()
            return
        try:
            if self.spec.is_3d:
                self._hover_pos = np.ascontiguousarray(data.pos, dtype="float64")
            else:
                from scipy.spatial import cKDTree

                self._hover_xy = np.ascontiguousarray(
                    data.pos[:, :2], dtype="float64")
                self._hover_tree = cKDTree(self._hover_xy)
            self._hover_rows = data.rows
        except Exception:  # noqa: BLE001 - hover is a nicety; never break render
            self._hover_tree = self._hover_rows = self._hover_xy = None
            self._hover_pos = None

    def _on_mouse_move(self, event) -> None:
        self._hover_cursor(event)
        if self.spec.is_bar or self.spec.is_hist or self.spec.is_cov:
            self._bar_hover(event)
            return
        if self.spec.is_3d:
            self._hover3d(event)
            return
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

    def _hover3d(self, event) -> None:
        """Nearest-point hover for the 3D scatter: project every drawn point to
        the screen, pick the closest to the cursor within a few pixels."""
        if (
            self._hover_pos is None
            or self._scatter is None
            or getattr(event, "pos", None) is None
        ):
            return
        if getattr(event, "buttons", None):  # a drag rotates/zooms — not a hover
            self._hide_tooltip()
            return
        try:
            proj = self._scatter.get_transform("visual", "canvas").map(
                self._hover_pos)
            w = proj[:, 3]
            front = w > 1e-6  # points at/behind the camera plane don't project
            if not front.any():
                self._hide_tooltip()
                return
            sx, sy = proj[:, 0] / w, proj[:, 1] / w
            d2 = (sx - event.pos[0]) ** 2 + (sy - event.pos[1]) ** 2
            d2[~front] = np.inf
            i = int(np.argmin(d2))
            if d2[i] > 12 ** 2:  # same pixel tolerance as the 2D hover
                self._hide_tooltip()
                return
            self._show_tooltip(i, float(sx[i]), float(sy[i]))
        except Exception:  # noqa: BLE001 - hover is a nicety; never break
            self._hide_tooltip()

    def _hover_text(self, i: int) -> str:
        rows = self._hover_rows
        if rows is None or i < 0 or i >= rows.height:
            return ""
        # Axis/colour columns follow renames via the spec; the part_id / layer
        # extras are raw, so map them through the rename map too.
        extras = [self._renames.get(c, c) for c in ("part_id", "layer")]
        cols = list(dict.fromkeys(
            [*self.spec.axes]
            + ([self.spec.color] if self.spec.color else [])
            + [c for c in extras if c in rows.columns]
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

    # -- export --------------------------------------------------------
    def save_image(self, path: str) -> bool:
        """Render the current canvas to an image file.

        The format is chosen from the file extension (PNG, JPEG, …). Returns
        True on success. The alpha channel is rendered opaque (the canvas has a
        solid background), so formats without alpha (JPEG) come out correctly.
        """
        if self._canvas is None:
            return False
        try:
            arr = np.ascontiguousarray(self._canvas.render(alpha=True))
        except Exception:  # noqa: BLE001 - GL read failure -> report to caller
            return False
        from PyQt6.QtGui import QImage

        h, w = arr.shape[:2]
        img = QImage(arr.data, w, h, 4 * w, QImage.Format.Format_RGBA8888)
        return bool(img.copy().save(path))  # copy() owns the pixels past scope

    # -- teardown ------------------------------------------------------
    def release(self) -> None:
        """Free render arrays and close the canvas (called on tab close)."""
        self._df = None
        self.raw = None
        self._scatter = None
        self._view = None
        self._hover_tree = self._hover_rows = self._hover_xy = None
        self._hover_pos = None
        self._title_label = None
        self._last_pos = self._last_colors = None
        self._bars = None
        self._bar_axis = None
        self._bar_labels = []
        self._bar_data = None
        self._contour_img = None
        self._contour_pts = None
        self._contour_data = None
        self._axis_labels = []
        self._hide_tooltip()
        if self._hl is not None:
            self._hl.hide()
            self._hl.deleteLater()
            self._hl = None
        if self._canvas is not None:
            try:
                self._canvas.close()
            except Exception:  # noqa: BLE001
                pass
            self._canvas = None
