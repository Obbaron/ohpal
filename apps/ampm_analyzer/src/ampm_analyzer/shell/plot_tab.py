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
from . import plotcontrols
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
# Distribution plots.
# (The curves' and violins' colours and widths are the data element's,
# see plot_elements.)
_KDE_FILL_ALPHA = 0.18   # under a KDE curve; fainter as curves multiply
_VIOLIN_EDGE = (0.16, 0.18, 0.22, 0.55)
_VIOLIN_INNER = (0.16, 0.18, 0.22, 0.85)  # whisker + quartile box
_LEGEND_PAD = 8          # px inside the legend box's frame
_LEGEND_INSET = 10       # px from the plot's edge, for a legend inside it
# Categorical scatter colours past this many come from the colormap (so the
# side panel's Map applies to them); fewer use the fixed palette.
_PALETTE_MAX = 8

# 3D view presets: (elevation, azimuth) in degrees for the turntable camera.
_CAMERA_PRESETS = {"top": (90.0, 0.0), "front": (0.0, 0.0),
                   "side": (0.0, 90.0), "iso": (30.0, 45.0)}
# Toolbar options that live on the spec (they change what is drawn, so a
# change re-renders); the rest are view state on the tab.
_SPEC_OPTIONS = ("show_box", "fill", "bandwidth", "bins", "sort",
                 "show_points", "show_lines", "show_ref")

# Editable elements. Chrome sizes below are the built-in look's; a bigger font
# grows its strip by the difference so text is never clipped.
_AXIS3D_KEYS = ("xaxis3d", "yaxis3d", "zaxis3d")
_TITLE_H, _XAXIS_H, _YAXIS_W = 28, 42, 62      # px, at the default font sizes
_AXIS_LABEL_MARGIN = 35                         # VisPy's default, px
_CBAR_LABEL_W, _CBAR_W = 18, 74
_CBAR_BOTTOM_PX = 14      # an automatic bar's thickness below the plot
_TITLE_INSET = 4         # px from the strip's end, for a left / right title
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
    # The set of toolbar controls that apply changed (a legend appeared, the
    # level lines became drawable...): the host rebuilds its toolbar.
    controlsChanged = pyqtSignal()
    # A drawing option changed the spec (a macro being recorded keeps it).
    specChanged = pyqtSignal()

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
        # Its query brings only the columns it needs (see plotneeds); True
        # once it fell back to every column.
        self._all_columns = False
        # A contour plot starts on the familiar filled-contour colours.
        self.cmap = "viridis" if spec.is_contour else DEFAULT_COLORMAP
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
        # Spatial 2D plots keep one X unit == one Y unit unless unlocked.
        self._equal_axes = True
        self._has_legend = False     # a colour bar / legend is on the plot
        self._legend_cmap = False    # categorical colours from the colormap
        self._contour_lines_ok = False  # the field allows level lines
        self._controls_sig = None    # the controls last reported

        self._canvas = None
        self._view = None
        self._scatter = None
        self._grid = None
        # Fixed grid cells that hold the colour bar, its name and the legend
        # (see _build_canvas). Empty, they are zero-sized: the plot gets the
        # room.
        self._slots: dict = {}
        self._cbar_orient = None     # "right" / "bottom": where the bar sits
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

        # Distribution plots. Curves (KDE, k-distance): one line each over a
        # translucent fill, plus a dashed guide line. Violins: one mesh of
        # shapes, their outlines, and the quartile boxes / medians. The data
        # behind them is kept, so recolouring doesn't recompute densities.
        # A legend of groups (KDE curves, a scatter coloured by text): a framed
        # box of swatches and names, beside the plot or inside a corner.
        self._legend = None          # its VisPy widget
        self._legend_parts: list = []
        self._legend_items = None    # (names, colours) shown, or None
        self._legend_auto = ""       # its automatic title (the group column)
        self._legend_size = (0.0, 0.0)
        self._legend_room = 0.0      # the plot height it was laid out for
        self._tick_sig: dict = {}    # each axis's tick settings, last applied
        self._grid_rgba = None       # the gridlines' colour, last applied
        self._curve_data = None
        self._curve_lines: list = []
        self._curve_fill = None
        self._ref_line = None
        self._ref_label = None
        self._violin_data = None
        self._violin_mesh = None
        self._violin_edges = None
        self._violin_marks = None
        self._dist_df = None      # the dataframe the cached data came from
        self._dist_key = None     # and the settings it was built with
        self._dist_data = None

        # Contour visuals: the filled bands (an image of the interpolated
        # field), the iso-lines on the band edges, the measured-point overlay.
        self._contour_img = None
        self._contour_pts = None
        self._contour_lines = None
        self._contour_data = None
        self._cbar_extra: list = []     # labels between the colour bar's ends
        self._cbar_extra_at: list = []  # their positions along it, 0..1
        self._cbar_spec = None          # (lo, hi, levels) the bar shows
        self._bar_w = 0.8               # drawn bar width, data units
        self._bar_outline = None

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
            k: pe.default_style(k, spec.kind) for k in pe.keys_for(spec)}
        self._data_key = pe.data_key(spec)
        self._take_bridged(self._el_style[self._data_key])
        self._selected: str | None = None
        self._hl: _Highlight | None = None
        self._press_pos = None       # left-button press, to tell click from drag
        self._rect_cache: dict = {}  # element rects, valid for one frame
        self._cbar_auto = ""         # the colour bar's automatic label
        self._hand = False           # pointing-hand cursor shown?
        self._fit_pending = False    # a Y-strip fit is queued for after a frame
        self._layout_sig = None      # where the view + axes sat last frame

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
            # Aligned to the plot's left / centre / right (Label centres).
            self._title_label._set_pos = self._place_title
            vcol = 0 if self.spec.is_3d else 1
            grid.add_widget(self._title_label, row=0, col=vcol)
            self._title_label.visible = self._show_title
            if self.spec.is_3d:
                # No left axis column in 3D — an empty grid column would take an
                # equal stretch and shove the view into the right half.
                view = grid.add_view(row=1, col=0)
                view.camera = scene.cameras.TurntableCamera(fov=45)
                below = 2
            else:
                view = grid.add_view(row=1, col=1)
                # aspect=1 → one X unit == one Y unit, so parts aren't skewed.
                # (Chart plots free it when they first render.)
                view.camera = scene.cameras.PanZoomCamera(
                    aspect=1 if self._equal_axes else None)
                below = 3
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
                for key, widget in (("xaxis", self._xaxis),
                                    ("yaxis", self._yaxis)):
                    self._own_ticks(key, widget.axis)
                self._gridlines = scene.visuals.GridLines(
                    color=(0, 0, 0, 0.12), parent=view.scene
                )
                # Blended over the background (VisPy adds them on, which
                # leaves a dark grid invisible).
                self._gridlines.set_gl_state("translucent", cull_face=False,
                                             depth_test=False)
                self._gridlines.order = -10  # under the data
                self._gridlines.visible = self._show_grid
            # Cells for the colour bar and the legend, always in the grid (an
            # empty column or row would take an equal share of the room) and
            # zero-sized until something is in them. Right of the plot: a
            # gap, the bar's name (vertical), then the bar or the legend.
            # Below it: a gap, the bar, its name.
            for name, row, col in (("gap_r", 1, vcol + 1), ("label_r", 1, vcol + 2),
                                   ("side", 1, vcol + 3), ("gap_b", below, vcol),
                                   ("bar_b", below + 1, vcol),
                                   ("label_b", below + 2, vcol)):
                slot = scene.Widget()
                self._slots[name] = slot
                self._size_slot(name, 0)
                grid.add_widget(slot, row=row, col=col)
            self._cbar_label = None
            view.events.resize.connect(self._on_view_resize)
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
        if self.spec.is_curve:
            self._render_curves()
            return
        if self.spec.is_violin:
            self._render_violins()
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
        # Bar width: a share of each bar's slot (a category, or a bin).
        slot = 1.0 if data.categorical else (data.width or 1.0)
        w = slot * float(self._ds("bar_width")) / 100.0
        self._bar_w = w
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
        self._set_bar_outline(verts, n)

        hvals = data.heights[np.isfinite(data.heights)]
        ymin = min(0.0, float(hvals.min()) if hvals.size else 0.0)
        ymax = max(0.0, float(hvals.max()) if hvals.size else 1.0)
        if ymax <= ymin:  # flat/degenerate heights → give the view a real span
            ymax = ymin + 1.0

        clo, chi = float(data.crange[0]), float(data.crange[1])
        if chi <= clo:  # flat values → a readable colourbar still needs a span
            chi = clo + 1.0
        self._set_colorbar(clo, chi, data.value_name)
        xlo = float(data.centers.min()) - w / 2
        xhi = float(data.centers.max()) + w / 2
        # Category bars get the text-label axis; histograms keep the numeric
        # x axis (the AxisWidget), so no rule or labels.
        if data.categorical:
            y_lo = self._draw_category_axis(
                data.centers, data.labels or [], ymin, ymax, xlo, xhi)
        else:
            self._clear_category_axis()
            y_lo = ymin
        self._data_bounds = (np.array([xlo, y_lo], "float32"),
                             np.array([xhi, ymax], "float32"))
        self._apply_elements()
        self._apply_visibility()
        first = not self._rendered_once
        self._rendered_once = True
        if self._view is not None and first:
            QTimer.singleShot(0, self.reset_view)

    def _set_bar_outline(self, verts, n: int) -> None:
        """A line round each bar, when asked for."""
        from vispy import scene

        if not self._ds("outline") or n == 0:
            if self._bar_outline is not None:
                self._bar_outline.parent = None
            return
        corners = verts[:, :2].reshape(n, 4, 2)
        segs = np.stack([corners, np.roll(corners, -1, axis=1)], axis=2)
        pos = segs.reshape(-1, 2).astype("float32")
        color = self._ds("outline_color")
        if self._bar_outline is None:
            self._bar_outline = scene.visuals.Line(
                pos=pos, connect="segments", color=color, width=1.0,
                parent=self._view.scene)
        else:
            self._bar_outline.set_data(pos=pos, color=color)
            if self._bar_outline.parent is None:
                self._bar_outline.parent = self._view.scene
        self._bar_outline.order = 1

    def _draw_category_axis(self, centers, labels, ymin, ymax, xlo, xhi) -> float:
        """A category x axis: a rule just below ``ymin`` and the category
        labels hanging under it (so they read as tick labels, not as text in
        the plot). Returns the lowest y the view should frame."""
        from vispy import scene

        for t in self._bar_labels:
            t.parent = None
        self._bar_labels = []
        gap = 0.045 * (ymax - ymin)
        axis_y = ymin - 0.35 * gap
        label_y = ymin - gap
        # The labels hang from just under the rule, so a bigger font grows
        # downwards, away from the data. (VisPy's "bottom" anchor is the
        # text's top edge in a y-up view.)
        hang_y = ymin - 0.45 * gap
        for i, label in enumerate(labels):
            t = scene.visuals.Text(
                label, pos=(float(centers[i]), hang_y), color=_AXIS_TEXT,
                anchor_x="center", anchor_y="bottom", font_size=9,
                parent=self._view.scene)
            self._bar_labels.append(t)
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
        return label_y  # frame the labels in (reset_view adds glyph room)

    def _clear_category_axis(self) -> None:
        for t in self._bar_labels:
            t.parent = None
        self._bar_labels = []
        if self._bar_axis is not None:
            self._bar_axis.parent = None

    # -- distribution plots: KDE, k-distance, violins ------------------
    def _chart_view(self) -> None:
        """Make the view a plain chart: the (data-less) scatter out of the
        scene (set_range walks every visual's bounds, and an un-fed Markers
        crashes on None data) and the aspect free (not spatial)."""
        if self._scatter is not None and self._scatter.parent is not None:
            self._scatter.parent = None
            self._scatter.visible = False
        try:
            self._view.camera.aspect = None
        except Exception:  # noqa: BLE001
            pass

    def _dist_cached(self, builder):
        """``builder``'s result for the current data and settings. Densities
        and nearest-neighbour distances are the expensive part, so they are
        built once and reused while only the colours change."""
        s = self.spec
        key = (builder.__name__, s.x, s.y, s.z, s.group_by, s.bandwidth,
               s.k, s.eps_xy, s.eps_z)
        if (self._dist_data is not None and self._dist_df is self._df
                and self._dist_key == key):
            return self._dist_data
        data = builder(self._df, s)
        self._dist_df, self._dist_key, self._dist_data = self._df, key, data
        return data

    def _render_curves(self) -> None:
        """KDE (one density per group, filled) or the k-distance curve."""
        from vispy import scene

        builder = plotdata.build_kde if self.spec.is_kde else plotdata.build_kdist
        try:
            data = self._dist_cached(builder)
        except KeyError as exc:
            self._show_overlay(str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            self._show_overlay(f"Could not plot: {exc}")
            return
        self._clear_overlay()
        self._chart_view()
        if self.spec.is_kde:
            data.colors = plotdata._sample_colors(data.n, self.cmap)
        else:
            data.colors = np.array([QColor(self._ds("line_color")).getRgbF()],
                                   "float32")
        self._curve_data = data

        # Filled areas under the KDE curves (one translucent mesh), then lines.
        for line in self._curve_lines:
            line.parent = None
        self._curve_lines = []
        x = np.asarray(data.x, dtype="float32")
        if self.spec.is_kde and self.spec.fill:
            m = x.size
            verts, faces, cols = [], [], []
            for c, ys in enumerate(data.ys):
                base = c * 2 * m
                v = np.empty((2 * m, 3), "float32")
                v[0::2, 0] = x
                v[0::2, 1] = 0.0
                v[1::2, 0] = x
                v[1::2, 1] = ys
                v[:, 2] = 0.0
                verts.append(v)
                j = np.arange(m - 1, dtype="uint32") * 2 + base
                faces.append(np.column_stack([j, j + 1, j + 3]))
                faces.append(np.column_stack([j, j + 3, j + 2]))
                fill = np.array(data.colors[c], "float32")
                pct = float(self._ds("fill_opacity") or 0)
                fill[3] = (pct / 100.0 if pct else
                           min(_KDE_FILL_ALPHA, max(0.03, 0.5 / data.n)))
                cols.append(np.tile(fill, (2 * m, 1)))
            V, F, C = np.vstack(verts), np.vstack(faces), np.vstack(cols)
            if self._curve_fill is None:
                self._curve_fill = scene.visuals.Mesh(
                    vertices=V, faces=F, vertex_colors=C, parent=self._view.scene)
                self._curve_fill.set_gl_state("translucent", depth_test=False)
            else:
                self._curve_fill.set_data(vertices=V, faces=F, vertex_colors=C)
                if self._curve_fill.parent is None:
                    self._curve_fill.parent = self._view.scene
            self._curve_fill.order = 0
        elif self._curve_fill is not None:
            self._curve_fill.parent = None
        for c, ys in enumerate(data.ys):
            line = scene.visuals.Line(
                pos=np.column_stack([x, np.asarray(ys, "float32")]),
                color=tuple(float(v) for v in data.colors[c]),
                width=float(self._ds("line_width")),
                method="agg", parent=self._view.scene)
            line.order = 1
            self._curve_lines.append(line)

        ymax = max(float(np.max(ys)) for ys in data.ys) if data.ys else 1.0
        xlo, xhi = float(x[0]), float(x[-1])
        if data.reference is not None and self.spec.show_ref:
            ymax = max(ymax, 1.08 * float(data.reference))  # guide + label room
        if ymax <= 0:
            ymax = 1.0
        self._set_reference(data, xlo, xhi, lift=0.012 * ymax)

        # KDE: a legend of the groups in the colour-bar column. One curve (or
        # the k-distance curve) needs none.
        if self.spec.is_kde and data.group_name and data.n > 1:
            self._set_legend(data.group_name, data.names, data.colors)
        else:
            self._hide_colorbar()
        self._full_range = None
        self._data_bounds = (np.array([xlo, 0.0], "float32"),
                             np.array([xhi, ymax], "float32"))
        self._apply_elements()
        self._apply_visibility()
        first = not self._rendered_once
        self._rendered_once = True
        if self._view is not None and first:
            QTimer.singleShot(0, self.reset_view)

    def _set_reference(self, data, xlo, xhi, lift: float = 0.0) -> None:
        """The k-distance curve's dashed guide at the XY radius (eps)."""
        from vispy import scene

        if data.reference is None or not self.spec.show_ref:
            for item in (self._ref_line, self._ref_label):
                if item is not None:
                    item.parent = None
            return
        y = float(data.reference)
        guide = QColor(self._ds("guide_color")).getRgbF()
        n = 60  # dashes: consecutive point pairs are drawn, gaps between
        pos = np.empty((2 * n, 2), "float32")
        pos[:, 0] = np.linspace(xlo, xhi, 2 * n + 1)[:2 * n]
        pos[:, 1] = y
        if self._ref_line is None:
            self._ref_line = scene.visuals.Line(
                pos=pos, color=guide, width=1.0, connect="segments",
                parent=self._view.scene)
        else:
            self._ref_line.set_data(pos=pos, color=guide)
            if self._ref_line.parent is None:
                self._ref_line.parent = self._view.scene
        self._ref_line.order = 2
        # Label at the right end, just above the line.
        text = f"eps = {_fmt(y)} mm"
        if self._ref_label is None:
            self._ref_label = scene.visuals.Text(
                text, pos=(xhi, y + lift), color=guide, anchor_x="right",
                anchor_y="top", font_size=9, parent=self._view.scene)
        else:
            self._ref_label.text = text
            self._ref_label.color = guide
            self._ref_label.pos = (xhi, y + lift)
            if self._ref_label.parent is None:
                self._ref_label.parent = self._view.scene

    def _render_violins(self) -> None:
        """One violin per category, coloured by its median, with an optional
        quartile box, whisker and median mark inside."""
        from vispy import scene

        try:
            data = self._dist_cached(plotdata.build_violins)
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
        self._chart_view()
        medians = np.array([st["median"] for st in data.stats], "float32")
        colors, clo, chi = plotdata._bar_colors(medians, self.cmap, self.crange)
        if self.crange is None:
            self.crange = (clo, chi)
        self._full_range = data.full_range
        data.colors = colors
        self._violin_data = data

        # The shapes: a strip of quads between the left and right outline.
        verts, faces, cols, edges, links = [], [], [], [], []
        base = 0
        for i, (ys, half) in enumerate(data.outlines):
            c = float(data.centers[i])
            m = ys.size
            v = np.zeros((2 * m, 3), "float32")
            v[0::2, 0] = c - half
            v[1::2, 0] = c + half
            v[0::2, 1] = ys
            v[1::2, 1] = ys
            verts.append(v)
            j = np.arange(m - 1, dtype="uint32") * 2 + base
            faces.append(np.column_stack([j, j + 1, j + 3]))
            faces.append(np.column_stack([j, j + 3, j + 2]))
            fill = np.array(colors[i], "float32")
            fill[3] = float(self._ds("fill_opacity")) / 100.0
            cols.append(np.tile(fill, (2 * m, 1)))
            # outline: up the right side, down the left, closed
            ring = np.vstack([np.column_stack([c + half, ys]),
                              np.column_stack([c - half, ys])[::-1]])
            start = sum(len(e) for e in edges)
            idx = np.arange(start, start + len(ring))
            links.append(np.column_stack([idx, np.roll(idx, -1)]))
            edges.append(ring.astype("float32"))
            base += 2 * m
        V, F, C = np.vstack(verts), np.vstack(faces), np.vstack(cols)
        if self._violin_mesh is None:
            self._violin_mesh = scene.visuals.Mesh(
                vertices=V, faces=F, vertex_colors=C, parent=self._view.scene)
            self._violin_mesh.set_gl_state("translucent", depth_test=False)
        else:
            self._violin_mesh.set_data(vertices=V, faces=F, vertex_colors=C)
            if self._violin_mesh.parent is None:
                self._violin_mesh.parent = self._view.scene
        self._violin_mesh.order = 0
        E, L = np.vstack(edges), np.vstack(links).astype("uint32")
        edge = QColor(self._ds("outline_color"))
        edge = (edge.redF(), edge.greenF(), edge.blueF(), _VIOLIN_EDGE[3])
        if self._violin_edges is None:
            self._violin_edges = scene.visuals.Line(
                pos=E, connect=L, color=edge, width=1.0,
                parent=self._view.scene)
        else:
            self._violin_edges.set_data(pos=E, connect=L, color=edge)
            if self._violin_edges.parent is None:
                self._violin_edges.parent = self._view.scene
        self._violin_edges.order = 1

        # Inside: whisker (min to max), quartile box, median mark: thin quads.
        y_all = [st[k] for st in data.stats for k in ("min", "max")]
        ymin, ymax = float(min(y_all)), float(max(y_all))
        if ymax <= ymin:
            ymax = ymin + 1.0
        if self.spec.show_box:
            qv, qf, qc = [], [], []

            def quad(x0, x1, y0, y1, rgba):
                b = sum(len(q) for q in qv)
                qv.append(np.array([[x0, y0, 0], [x1, y0, 0], [x1, y1, 0],
                                    [x0, y1, 0]], "float32"))
                qf.append(np.array([[b, b + 1, b + 2], [b, b + 2, b + 3]],
                                   "uint32"))
                qc.append(np.tile(np.array(rgba, "float32"), (4, 1)))

            tick = 0.004 * (ymax - ymin)  # the median mark's half height
            for i, st in enumerate(data.stats):
                c = float(data.centers[i])
                quad(c - 0.006, c + 0.006, st["min"], st["max"], _VIOLIN_INNER)
                quad(c - 0.045, c + 0.045, st["q1"], st["q3"], _VIOLIN_INNER)
                quad(c - 0.045, c + 0.045, st["median"] - tick,
                     st["median"] + tick, (1.0, 1.0, 1.0, 1.0))
            QV, QF, QC = np.vstack(qv), np.vstack(qf), np.vstack(qc)
            if self._violin_marks is None:
                self._violin_marks = scene.visuals.Mesh(
                    vertices=QV, faces=QF, vertex_colors=QC,
                    parent=self._view.scene)
                # Same depth for every quad: draw in order (the median mark
                # goes over its box) instead of depth-testing it away.
                self._violin_marks.set_gl_state("translucent", depth_test=False)
            else:
                self._violin_marks.set_data(vertices=QV, faces=QF,
                                            vertex_colors=QC)
                if self._violin_marks.parent is None:
                    self._violin_marks.parent = self._view.scene
            self._violin_marks.order = 2
        elif self._violin_marks is not None:
            self._violin_marks.parent = None

        self._set_colorbar(clo, chi if chi > clo else clo + 1.0,
                           f"{data.value_name} (median)")
        xlo, xhi = float(data.centers.min()) - 0.5, float(data.centers.max()) + 0.5
        y_lo = self._draw_category_axis(data.centers, data.labels, ymin, ymax,
                                        xlo, xhi)
        self._data_bounds = (np.array([xlo, y_lo], "float32"),
                             np.array([xhi, ymax], "float32"))
        self._apply_elements()
        self._apply_visibility()
        first = not self._rendered_once
        self._rendered_once = True
        if self._view is not None and first:
            QTimer.singleShot(0, self.reset_view)

    def _curve_hover(self, event) -> None:
        """The curve nearest the pointer (KDE: its group) at the pointer's x."""
        data = self._curve_data
        if (data is None or not self._curve_lines
                or getattr(event, "pos", None) is None):
            return
        if getattr(event, "buttons", None):
            self._hide_tooltip()
            return
        try:
            line = self._curve_lines[0]
            dx = float(line.get_transform("canvas", "visual").map(event.pos)[0])
            x = data.x
            if not (x[0] <= dx <= x[-1]):
                self._hide_tooltip()
                return
            j = int(np.clip(np.searchsorted(x, dx), 0, x.size - 1))
            pts = np.column_stack([np.full(len(data.ys), x[j]),
                                   [float(ys[j]) for ys in data.ys]])
            canvas = np.atleast_2d(
                line.get_transform("visual", "canvas").map(pts))
            dist = np.abs(canvas[:, 1] - float(event.pos[1]))
            c = int(np.argmin(dist))
            if dist[c] > 40:
                self._hide_tooltip()
                return
            y = float(data.ys[c][j])
            if self.spec.is_kdist:
                lines = [f"rank: {int(x[j]):,} of {x.size:,}",
                         f"{data.y_name}: {_fmt(y)}"]
            else:
                lines = ([f"{data.group_name}: {data.names[c]}"]
                         if data.group_name else [])
                lines += [f"{data.x_name}: {_fmt(float(x[j]))}",
                          f"density: {_fmt(y)}",
                          f"n = {data.counts[c]:,}"]
            if self._tooltip is None:
                self._tooltip = PlotTooltip(self._canvas.native)
            native = self._canvas.native
            self._tooltip.show_at((float(canvas[c, 0]), float(canvas[c, 1])),
                                  lines, data.colors[c],
                                  (native.width(), native.height()))
        except Exception:  # noqa: BLE001
            self._hide_tooltip()

    def _violin_hover(self, event) -> None:
        """A violin's quartiles and range under the pointer."""
        data = self._violin_data
        if (data is None or self._violin_mesh is None
                or getattr(event, "pos", None) is None):
            return
        if getattr(event, "buttons", None):
            self._hide_tooltip()
            return
        try:
            mesh = self._violin_mesh
            dx, dy = mesh.get_transform("canvas", "visual").map(event.pos)[:2]
            i = int(np.argmin(np.abs(data.centers - dx)))
            st = data.stats[i]
            room = 0.02 * ((max(s["max"] for s in data.stats)
                            - min(s["min"] for s in data.stats)) or 1.0)
            if (abs(dx - float(data.centers[i])) > 0.45
                    or not (st["min"] - room <= dy <= st["max"] + room)):
                self._hide_tooltip()
                return
            px, py = mesh.get_transform("visual", "canvas").map(
                [float(data.centers[i]), st["median"]])[:2]
            lines = [f"{data.x_name}: {st['key']}", f"n = {st['n']:,}",
                     f"max: {_fmt(st['max'])}", f"Q3: {_fmt(st['q3'])}",
                     f"median: {_fmt(st['median'])}", f"Q1: {_fmt(st['q1'])}",
                     f"min: {_fmt(st['min'])}"]
            if self._tooltip is None:
                self._tooltip = PlotTooltip(self._canvas.native)
            native = self._canvas.native
            self._tooltip.show_at((px, py), lines, data.colors[i],
                                  (native.width(), native.height()))
        except Exception:  # noqa: BLE001
            self._hide_tooltip()

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

        # Filled bands: the interpolated surface, each sample coloured by the
        # level band its value falls in. Empty regions stay clear.
        lo, hi = float(data.crange[0]), float(data.crange[1])
        levels = plotdata.nice_levels(lo, hi)
        field = data.field
        rgba = plotdata.band_image(field, levels, self.cmap)

        xmin, xmax, ymin, ymax = data.extent
        ny, nx = field.shape
        dx = (xmax - xmin) / (nx - 1) if nx > 1 and xmax > xmin else 1.0
        dy = (ymax - ymin) / (ny - 1) if ny > 1 and ymax > ymin else 1.0

        if self._contour_img is None:
            self._contour_img = scene.visuals.Image(
                rgba, parent=self._view.scene, interpolation="bilinear")
        else:
            self._contour_img.set_data(rgba)
            if self._contour_img.parent is None:
                self._contour_img.parent = self._view.scene
        # Sample (col, row) sits at data (xmin + col*dx, ymin + row*dy); an
        # image texel is drawn around its sample, hence the half-step shift.
        self._contour_img.transform = STTransform(
            scale=(dx, dy), translate=(xmin - dx / 2, ymin - dy / 2))
        self._contour_img.order = 0
        self._contour_img.visible = True

        # Thin iso-lines on the band edges sharpen the bands, as in a
        # filled-contour plot. (Skipped over a field with empty regions.)
        inner = [float(v) for v in levels[1:-1]]
        self._contour_lines_ok = bool(inner) and bool(np.isfinite(field).all())
        if self._contour_lines_ok and self.spec.show_lines:
            lc = QColor(self._ds("line_color"))
            lev = (lc.redF(), lc.greenF(), lc.blueF(),
                   float(self._ds("line_opacity")) / 100.0)
            width = float(self._ds("line_width"))
            if (self._contour_lines is not None
                    and float(self._contour_lines.width) != width):
                self._contour_lines.parent = None  # a new width: made again
                self._contour_lines = None
            if self._contour_lines is None:
                self._contour_lines = scene.visuals.Isocurve(
                    field, levels=inner, color_lev=lev,
                    width=width, antialias=True,
                    parent=self._view.scene)
                self._contour_lines.set_gl_state("translucent", depth_test=False)
            else:
                self._contour_lines.levels = inner
                self._contour_lines.color = lev
                self._contour_lines.set_data(field)
                if self._contour_lines.parent is None:
                    self._contour_lines.parent = self._view.scene
            self._contour_lines.transform = STTransform(
                scale=(dx, dy), translate=(xmin, ymin))
            self._contour_lines.order = 1
            self._contour_lines.visible = True
        elif self._contour_lines is not None:
            self._contour_lines.visible = False

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
                edge_color=(0, 0, 0, 0.7), edge_width=1,
                size=float(self._ds("point_size")), symbol="disc")
            self._contour_pts.antialias = 1
            self._contour_pts.order = 2   # on top of the bands and lines
            self._contour_pts.visible = True
        elif self._contour_pts is not None:
            self._contour_pts.visible = False

        # The colour bar shows the same bands, labelled at round levels.
        self._set_colorbar(float(levels[0]), float(levels[-1]), data.value_name,
                           levels=levels)
        self._data_bounds = (np.array([xmin, ymin], "float32"),
                             np.array([xmax, ymax], "float32"))
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
            w = self._bar_w
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
                bw = data.width or w
                head = (f"{data.x_name}: {_fmt(data.centers[i] - bw / 2)}"
                        f"–{_fmt(data.centers[i] + bw / 2)}")
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
        self._legend_cmap = False
        if isinstance(leg, tuple) and leg and leg[0] == "colorbar":
            _, lo, hi, name = leg
            self._set_colorbar(lo, hi, name)
        elif isinstance(leg, list) and leg:
            # Coloured by a text column: a legend box of its categories.
            names = [str(n) for n, _ in leg]
            colors = np.array([c for _, c in leg], "float32")
            self._legend_cmap = len(names) > _PALETTE_MAX
            self._set_legend(self.spec.color or "", names, colors)
        else:
            self._hide_colorbar()

    def _hide_colorbar(self) -> None:
        """No colour bar or legend on this plot (single colour, one curve)."""
        self._has_legend = False
        self._legend_items = None
        self._cbar_spec = None
        self._set_cbar_ticks()
        self._apply_visibility()

    # -- colour bar ----------------------------------------------------
    def _set_colorbar(self, lo, hi, name, levels=None) -> None:
        """Show the colour bar for [lo, hi]. With ``levels`` (a contour plot's
        band edges) the bar is drawn in the same discrete bands and labelled
        at round levels along its length, not only at its ends."""
        from vispy.color import Colormap

        self._has_legend = True
        self._legend_items = None
        if levels is not None and len(levels) > 2:
            colors = plotdata.band_colors(np.asarray(levels), self.cmap)
            cm = Colormap(colors, controls=np.linspace(0.0, 1.0, len(colors) + 1),
                          interpolation="zero")
        else:
            levels = None
            cm = Colormap(colormap_stops(self.cmap))
        self._cbar_auto = str(name)
        self._cbar_spec = (float(lo), float(hi), levels)
        self._cbar_cm = cm
        self._ensure_cbar()
        self._cbar.cmap = cm
        self._set_cbar_ticks()
        self._apply_visibility()
        self._apply_element("cbar")  # label text + fonts (a new bar included)

    def _ensure_cbar(self) -> None:
        """The colour bar widget (and its name) in the cells for the chosen
        position; made again when the position changes (VisPy fixes a bar's
        orientation when it is made)."""
        from vispy import scene

        orient = self._el_style["cbar"].get("orient", "right")
        if self._cbar is not None and self._cbar_orient == orient:
            return
        old_bar, old_label = self._cbar, self._cbar_label
        for widget, slot in ((old_bar, "side" if self._cbar_orient == "right"
                              else "bar_b"),
                             (old_label, "label_r" if self._cbar_orient == "right"
                              else "label_b")):
            if widget is not None and widget in self._slots[slot]._widgets:
                self._slots[slot].remove_widget(widget)
        for t in self._cbar_extra:
            t.parent = None
        self._cbar_extra, self._cbar_extra_at = [], []
        right = orient == "right"
        # No built-in label: the name is a separate Label in its own cell, so
        # it sits in whitespace and never overlaps the bar or its numbers.
        bar = scene.ColorBarWidget(
            cmap=getattr(self, "_cbar_cm", "viridis"),
            orientation="left" if right else "bottom", label="", clim=("", ""),
            border_width=1, border_color="#888888")
        bar.bgcolor = _BG
        base = bar._calc_size

        def calc_size(bar=bar, base=base):
            major, minor = base()
            px = float(self._el_style["cbar"].get("thickness") or 0)
            if px > 0:  # a set thickness, in pixels
                minor = px
            elif not right:  # automatic, across a wide plot: a slim bar
                minor = _CBAR_BOTTOM_PX
            # A collapsed cell (bar hidden) must still give VisPy a size.
            major = max(float(major), 4.0)
            return (major, min(max(float(minor), 1.0), major))

        bar._calc_size = calc_size
        label = scene.Label("", rotation=-90 if right else 0,
                            color=_AXIS_TEXT, font_size=9)
        self._slots["side" if right else "bar_b"].add_widget(bar)
        self._slots["label_r" if right else "label_b"].add_widget(label)
        self._cbar, self._cbar_label, self._cbar_orient = bar, label, orient

    def _cbar_number(self, value: float) -> str:
        st = self._el_style["cbar"]
        return pe.format_number(value, st.get("num_format", "auto"),
                                st.get("num_decimals", 2))

    def _set_cbar_ticks(self) -> None:
        """The numbers along the bar. VisPy's bar labels only its two ends;
        the labels between them (a banded bar's round levels, or the ticks
        asked for in the editor) are extra text placed along it."""
        from vispy import scene

        for t in self._cbar_extra:
            t.parent = None
        self._cbar_extra, self._cbar_extra_at = [], []
        if self._cbar is None or self._cbar_spec is None:
            return
        lo, hi, levels = self._cbar_spec
        st = self._el_style["cbar"]
        auto = st.get("num_format", "auto") == "auto"
        marks = []  # (fraction along the bar, text) between the ends
        if levels is not None:
            last = len(levels) - 1
            texts = dict(plotdata.level_labels(np.asarray(levels)))
            if not auto:
                texts = {i: self._cbar_number(float(levels[i])) for i in texts}
            self._cbar.clim = (texts.get(0, ""), texts.get(last, ""))
            if hi > lo:
                marks = [((float(levels[i]) - lo) / (hi - lo), t)
                         for i, t in texts.items() if i not in (0, last)]
        else:
            self._cbar.clim = ((_sig(lo), _sig(hi)) if auto else
                               (self._cbar_number(lo), self._cbar_number(hi)))
            n = int(st.get("num_ticks") or 0)
            if n and hi > lo:
                for v in pe.nice_ticks(lo, hi, max(2, n)):
                    frac = (v - lo) / (hi - lo)
                    if 0.08 < frac < 0.92:  # clear of the end numbers
                        marks.append((frac, self._cbar_number(v)))
        for frac, text in marks:
            label = scene.visuals.Text(
                text, parent=self._cbar, color="black", font_size=12)
            self._cbar_extra.append(label)
            self._cbar_extra_at.append(frac)
        self._place_cbar_ticks()

    def _place_cbar_ticks(self) -> None:
        """Put the end numbers (below a horizontal bar, where VisPy would put
        them on its ends) and the extra labels between them (VisPy places
        its own labels again whenever the bar is laid out)."""
        if self._cbar is None:
            return
        try:
            low, high = self._cbar.ticks
            if self._cbar_orient == "bottom":
                cb = self._cbar._colorbar
                cx, cy = (float(v) for v in np.asarray(cb.pos).reshape(-1)[:2])
                hw, hh = (float(v) for v in cb._halfdim)
                for tick, x in ((low, cx - hw), (high, cx + hw)):
                    want = (x, cy + hh + 3.0)
                    old = np.asarray(tick.pos, dtype="float64").reshape(-1)[:2]
                    if not np.allclose(old, want, atol=0.25):
                        tick.pos = want
                    if tuple(tick.anchors) != ("center", "bottom"):
                        tick.anchors = ("center", "bottom")
            if not self._cbar_extra:
                return
            p0 = np.asarray(low.pos, dtype="float64").reshape(-1)[:2]
            p1 = np.asarray(high.pos, dtype="float64").reshape(-1)[:2]
            for label, frac in zip(self._cbar_extra, self._cbar_extra_at):
                pos = p0 + (p1 - p0) * frac
                old = np.asarray(label.pos, dtype="float64").reshape(-1)[:2]
                if not np.allclose(old, pos, atol=0.25):
                    label.pos = (float(pos[0]), float(pos[1]))
                label.anchors = low.anchors
                label.visible = bool(self._cbar.visible)
        except Exception:  # noqa: BLE001 - labels are cosmetic
            pass

    # -- legend box ----------------------------------------------------
    def _set_legend(self, name: str, names: list, colors) -> None:
        """A legend of groups: one swatch and name per group, in a box."""
        self._has_legend = True
        self._cbar_spec = None
        self._legend_auto = str(name)
        self._legend_items = (list(names), np.asarray(colors, "float32"))
        self._apply_visibility()
        self._apply_element("legend")

    def _legend_place(self) -> str:
        return self._el_style.get("legend", {}).get("place", "outside")

    def _build_legend(self) -> None:
        """Lay the legend out: title, then the rows, as many as fit beside
        the plot (the rest are counted on a last row)."""
        from vispy import scene

        st = self._el_style.get("legend")
        if st is None or self._legend_items is None or self._view is None:
            return
        place = self._legend_place()
        host = self._slots["side"] if place == "outside" else self._view
        if self._legend is None or self._legend.parent is not host:
            if self._legend is not None:
                self._legend.parent = None
            self._legend = scene.Widget(parent=host)
            self._legend_parts = []
        for part in self._legend_parts:
            part.parent = None
        self._legend_parts = []
        names, colors = self._legend_items

        def metrics(prefix):
            font = QFont(st.get(prefix + "font") or pe.DEFAULT_FONT)
            font.setPixelSize(max(1, int(round(self._px(st[prefix + "size"])))))
            font.setBold(bool(st.get(prefix + "bold", False)))
            font.setItalic(bool(st.get(prefix + "italic", False)))
            return QFontMetricsF(font)

        title = st.get("text") or self._legend_auto
        fm_t, fm_n = metrics(""), metrics("name_")
        row_h = max(fm_n.height() * 1.35, 10.0)
        swatch = max(6.0, fm_n.height() * 0.7)
        title_h = fm_t.height() * 1.4 if title else 0.0
        try:
            self._legend_room = float(self._view.size[1])
        except Exception:  # noqa: BLE001
            self._legend_room = 400.0
        room = self._legend_room - (
            0 if place == "outside" else 2 * _LEGEND_INSET)
        fit = max(1, int((room - 2 * _LEGEND_PAD - title_h) // row_h))
        rows = list(names)
        if len(rows) > fit:  # the rest, counted
            rows = rows[:max(0, fit - 1)] + [f"+ {len(names) - fit + 1} more"]
        width = fm_t.horizontalAdvance(title) if title else 0.0
        for text in rows:
            width = max(width, swatch + 6 + fm_n.horizontalAdvance(text))
        width += 2 * _LEGEND_PAD
        height = 2 * _LEGEND_PAD + title_h + row_h * len(rows)
        self._legend_size = (float(np.ceil(width)), float(np.ceil(height)))
        y = float(_LEGEND_PAD)
        if title:
            t = scene.visuals.Text(title, parent=self._legend, anchor_x="left",
                                   anchor_y="center",
                                   pos=(_LEGEND_PAD, y + title_h / 2))
            _style_text(t, st)
            self._legend_parts.append(t)
            y += title_h
        # Every row has a swatch except a last "+ n more".
        shown = list(range(len(rows) if len(rows) == len(names)
                           else len(rows) - 1))
        if shown:
            centres = np.array([[_LEGEND_PAD + swatch / 2, y + (i + 0.5) * row_h]
                                for i in shown], "float32")
            marks = scene.visuals.Markers(parent=self._legend)
            marks.set_data(centres, face_color=colors[shown], size=swatch,
                           symbol="square", edge_width=0)
            marks.antialias = 0
            self._legend_parts.append(marks)
        name_st = {"font": st.get("name_font"), "size": st["name_size"],
                   "color": st.get("name_color", _AXIS_TEXT)}
        for i, text in enumerate(rows):
            t = scene.visuals.Text(
                text, parent=self._legend, anchor_x="left", anchor_y="center",
                pos=(_LEGEND_PAD + swatch + 6, y + (i + 0.5) * row_h))
            _style_text(t, name_st)
            self._legend_parts.append(t)
        frame = bool(st.get("frame", True))
        self._legend.border_color = st.get("frame_color") if frame else None
        self._legend.border_width = 1 if frame else 0
        # Inside the plot it covers the data, so it gets a backing.
        self._legend.bgcolor = ((1, 1, 1, 0.92) if place != "outside"
                                else (1, 1, 1, 0.55) if frame else None)
        self._legend.size = self._legend_size
        self._place_legend()

    def _on_view_resize(self, _event=None) -> None:
        """The plot area changed size: re-fit the legend's rows to it."""
        if self._legend is None or not self._legend.visible:
            return
        try:
            room = float(self._view.size[1])
        except Exception:  # noqa: BLE001
            return
        if abs(room - self._legend_room) > 16:
            self._legend_room = room
            QTimer.singleShot(0, lambda: self._apply_element("legend"))
        else:
            self._place_legend()

    def _place_legend(self) -> None:
        """Pin the legend to its corner (the plot's size may have changed)."""
        if self._legend is None or self._view is None:
            return
        place = self._legend_place()
        w, h = self._legend_size
        if place == "outside":
            pos = (6.0, 0.0)
        else:
            vw, vh = (float(v) for v in self._view.size)
            x = _LEGEND_INSET if place.endswith("left") else vw - w - _LEGEND_INSET
            y = _LEGEND_INSET if place.startswith("top") else vh - h - _LEGEND_INSET
            pos = (max(0.0, x), max(0.0, y))
        if tuple(round(float(v), 1) for v in self._legend.pos) != tuple(
                round(v, 1) for v in pos):
            self._legend.pos = pos

    # -- what is shown, and the room it takes ---------------------------
    def _size_slot(self, name: str, px: float) -> None:
        slot = self._slots.get(name)
        if slot is None:
            return
        px = max(0.0, float(px))
        if name.endswith("_b"):
            slot.height_min = slot.height_max = px
        else:
            slot.width_min = slot.width_max = px

    def _layout_side(self) -> None:
        """Size the colour bar's and legend's cells for what is shown. A
        hidden bar or legend takes no room: the plot gets it."""
        if not self._slots:
            return
        sizes = dict.fromkeys(self._slots, 0.0)
        legend = self._show_legend and self._has_legend
        st = self._el_style["cbar"]
        if legend and self._legend_items is not None:
            if self._legend_place() == "outside":
                sizes["side"] = self._legend_size[0] + 6.0
        elif legend and self._cbar is not None:
            gap = float(st.get("gap", 0))
            label = self._cbar_label_extent(st)
            if self._cbar_orient == "bottom":
                sizes.update(gap_b=gap + 4.0, bar_b=self._cbar_extent(st),
                             label_b=label)
            else:
                sizes.update(gap_r=gap, label_r=label,
                             side=self._cbar_extent(st))
        for name, px in sizes.items():
            self._size_slot(name, px)
        self._relayout()

    def _apply_visibility(self) -> None:
        if self._yaxis is not None:
            self._yaxis.visible = self._show_axes
        if self._xaxis is not None:
            # Category bars use text labels, not the numeric x axis; histograms
            # keep the numeric x axis.
            self._xaxis.visible = self._show_axes and not (
                self.spec.is_bar or self.spec.is_cov or self.spec.is_violin)
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
        legend = self._show_legend and self._has_legend
        box = legend and self._legend_items is not None
        if self._cbar is not None:
            self._cbar.visible = legend and not box
        if self._cbar_label is not None:
            self._cbar_label.visible = legend and not box
        if box:
            self._build_legend()
        if self._legend is not None:
            self._legend.visible = box
        # Hidden axes give their strips back to the plot.
        for key in ("xaxis", "yaxis"):
            if key in self._el_style:
                self._apply_element(key)
        self._layout_side()
        self._elements_changed()  # a hidden element can't stay outlined
        self._note_controls()

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

    # -- contextual controls (what the toolbar offers for this plot) -----
    def _is_spatial(self) -> bool:
        """A 2D plot of positions (scatter, layer views): equal axes apply."""
        s = self.spec
        return not (s.is_3d or s.is_bar or s.is_hist or s.is_cov
                    or s.is_contour or s.is_curve or s.is_violin)

    def _has_points(self) -> bool:
        """Drawn as markers whose size, symbol and opacity can be set."""
        return self.spec.is_3d or self._is_spatial()

    def controls(self) -> list:
        """The toolbar controls that apply to this plot right now: its view's
        controls (``plotcontrols``), less any with nothing to act on (a
        legend needs one on the plot, a bounding box a 3D scene, the level
        lines a field without gaps, the eps guide a k-distance curve)."""
        from dataclasses import replace

        s = self.spec
        curve = self._curve_data
        out = []
        for c in plotcontrols.controls_for(s.kind):
            k = c.key
            if k == "bbox" and not s.is_3d:
                continue
            if k == "legend" and not self._has_legend:
                continue
            if k == "show_lines" and not self._contour_lines_ok:
                continue
            if k == "show_ref" and (curve is None or curve.reference is None):
                continue
            if k in ("layer_prev", "layer_next") and len(self._layers) < 2:
                continue
            if k == "bins" and s.bins not in [v for v, _ in c.choices]:
                c = replace(c, choices=tuple(sorted(
                    (*c.choices, (s.bins, str(s.bins))))))
            out.append(c)
        return out

    def control_value(self, key: str):
        """A control's current value (on/off, or the chosen value); None for
        one-shot controls."""
        flags = {
            "axes": self._show_axes, "grid": self._show_grid,
            "bbox": self._show_bbox, "legend": self._show_legend,
            "title": self._show_title, "equal_axes": self._equal_axes,
        }
        if key in flags:
            return flags[key]
        if key in _SPEC_OPTIONS:
            return getattr(self.spec, key)
        return None

    def set_control(self, key: str, value=None) -> None:
        """Apply a toolbar control by key. (Screenshot belongs to the host,
        which asks where to save.)"""
        toggles = {
            "axes": self.set_axes_visible, "grid": self.set_grid_visible,
            "bbox": self.set_bbox_visible, "legend": self.set_legend_visible,
            "title": self.set_title_visible, "equal_axes": self.set_equal_axes,
        }
        if key in toggles:
            toggles[key](bool(value))
        elif key == "reset_view":
            self.reset_view()
        elif key == "camera":
            self.set_camera_view(str(value))
        elif key == "layer_prev":
            self.step_layer(-1)
        elif key == "layer_next":
            self.step_layer(1)
        elif key in _SPEC_OPTIONS:
            self.set_option(key, value)

    def _note_controls(self) -> None:
        """Tell the host when the controls on offer change."""
        sig = tuple((c.key, c.choices) for c in self.controls())
        if sig != self._controls_sig:
            self._controls_sig = sig
            self.controlsChanged.emit()

    def set_equal_axes(self, on: bool) -> None:
        """Lock (or free) one X unit to one Y unit, then re-frame."""
        self._equal_axes = bool(on)
        if self._view is None or not self._is_spatial():
            return
        try:
            self._view.camera.aspect = 1 if self._equal_axes else None
        except Exception:  # noqa: BLE001
            return
        self.reset_view()

    def set_camera_view(self, name: str) -> None:
        """Turn a 3D plot to a preset angle (top, front, side, iso)."""
        angles = _CAMERA_PRESETS.get(name)
        if angles is None or self._view is None or not self.spec.is_3d:
            return
        cam = self._view.camera
        cam.elevation, cam.azimuth = angles
        self.reset_view()

    def step_layer(self, step: int) -> None:
        """Layer Viewer: move the scrubber one layer back or on."""
        if self._slider is None:
            return
        i = self._slider.value() + int(step)
        self._slider.setValue(max(0, min(self._slider.maximum(), i)))

    def set_option(self, key: str, value) -> None:
        """Change one of the plot's drawing options and redraw."""
        from dataclasses import replace

        old = getattr(self.spec, key)
        value = type(old)(value)
        if value == old:
            return
        # A new spec, not an edit: a macro step already saved keeps the spec
        # it recorded (one being recorded follows it: specChanged).
        self.spec = replace(self.spec, **{key: value})
        if key == "bins":
            self.crange = None  # new bins, new counts: re-detect the colours
        self._render()
        self.specChanged.emit()
        if key in ("bins", "bandwidth", "show_ref", "show_points"):
            QTimer.singleShot(0, self.reset_view)  # the extent moved

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

    def _place_title(self) -> None:
        """Put the title text at the left, centre or right of its strip."""
        label = self._title_label
        if label is None:
            return
        tv, rect = label._text_visual, label.rect
        align = self._el_style.get("title", {}).get("align", "center")
        cy = rect.center[1]
        if align == "left":
            pos, anchors = (rect.left + _TITLE_INSET, cy), ("left", "center")
        elif align == "right":
            pos, anchors = (rect.right - _TITLE_INSET, cy), ("right", "center")
        else:
            pos, anchors = rect.center, ("center", "center")
        if tuple(tv.anchors) != anchors:
            tv.anchors = anchors
        tv.pos = pos

    def _title_height(self) -> float:
        size = self._el_style["title"]["size"]
        return max(18.0, _TITLE_H + 1.5 * (self._px(size) - self._px(13)))

    def _auto_text(self, key: str) -> str:
        """An element's automatic text — what it shows with no override."""
        if key in ("xaxis", "xaxis3d"):
            if key == "xaxis" and self._curve_data is not None:
                return str(self._curve_data.x_name)
            return str(self.spec.x or "")
        if key == "yaxis":
            if self._bar_data is not None:  # bars measure count / CoV / value
                return str(self._bar_data.value_name)
            if self._curve_data is not None:  # density / k-distance
                return str(self._curve_data.y_name)
            return str(self.spec.y or "")
        if key == "yaxis3d":
            return str(self.spec.y or "")
        if key == "zaxis3d":
            return str(self.spec.z or "")
        if key == "cbar":
            return self._cbar_auto
        if key == "legend":
            return self._legend_auto
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
        if key == "legend":
            return self._legend is not None and bool(self._legend.visible)
        if key == self._data_key:
            return self._data_present()
        return False

    def _data_present(self) -> bool:
        """The data is drawn (something to click and style)."""
        k = self._data_key
        if k == "data_points":
            return (self._last_pos is not None and self._scatter is not None
                    and self._scatter.parent is not None)
        if k == "data_bars":
            return self._bar_data is not None and self._bars is not None
        if k in ("data_curves", "data_kdist"):
            return self._curve_data is not None and bool(self._curve_lines)
        if k == "data_violins":
            return self._violin_data is not None
        if k == "data_contour":
            return self._contour_data is not None
        return False

    # The data's settings shared with the side panel's Points / Colour
    # controls live on the plot; the element shows (and saves) them.
    def _bridged(self) -> dict:
        return {"symbol": self._symbol, "size": int(self._base_size),
                "opacity": int(round(self._opacity * 100)), "cmap": self.cmap,
                "scale": self.scale}

    def _take_bridged(self, style: dict) -> None:
        """A new plot starts from its data element's default."""
        if "symbol" in style:
            self._symbol = style["symbol"]
        if "size" in style:
            self._base_size = max(1, int(style["size"]))
        if "opacity" in style:
            self._opacity = max(0.0, min(1.0, style["opacity"] / 100.0))
        if "cmap" in style:
            self.cmap = style["cmap"]
        if "scale" in style:
            self.scale = style["scale"]

    def _ds(self, name: str):
        """One of the data element's settings."""
        st = self._el_style.get(self._data_key, {})
        return st.get(name, pe.ELEMENTS[self._data_key].defaults.get(name))

    def element_values(self, key: str) -> dict:
        """The element's current style, for the editor."""
        vals = dict(self._el_style.get(key, {}))
        if key == "title":
            vals["text"] = self.title
        if key == self._data_key:
            vals.update({k: v for k, v in self._bridged().items() if k in vals})
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
        if key in ("xaxis", "yaxis") and name.startswith("grid_"):
            # One set of gridlines: either axis's editor sets it.
            other = self._el_style.get("yaxis" if key == "xaxis" else "xaxis")
            if other is not None:
                other[name] = value
        if key == self._data_key:
            self._apply_data({name: value})
        else:
            self._apply_element(key)
        self._elements_changed()

    def reset_element(self, key: str, builtin: bool = False) -> None:
        """Back to the default for new plots (or the built-in look). The text
        is kept — only the styling resets."""
        if key not in self._el_style:
            return
        kind = self.spec.kind
        fresh = (pe.builtin_style(key, kind) if builtin
                 else pe.default_style(key, kind))
        if "text" in fresh:
            fresh["text"] = self._el_style[key].get("text", "")
        self._el_style[key] = fresh
        if key in ("xaxis", "yaxis"):
            other = self._el_style.get("yaxis" if key == "xaxis" else "xaxis")
            if other is not None:
                other.update({k: v for k, v in fresh.items()
                              if k.startswith("grid_")})
        if key == self._data_key:
            self._apply_data(fresh)
        else:
            self._apply_element(key)
        self._elements_changed()

    def save_element_default(self, key: str) -> None:
        """Make this element's styling the default for new plots."""
        if key in self._el_style:
            pe.save_default(key, self.element_values(key), self.spec.kind)

    def _apply_data(self, changes: dict) -> None:
        """Apply data settings: the shared ones through the plot's own
        setters (as the side panel does), the rest by drawing again."""
        setters = {"symbol": self.set_marker_symbol,
                   "size": self.set_marker_size, "opacity": self.set_opacity,
                   "cmap": self.set_colormap, "scale": self.set_scale}
        live = self._bridged()
        redraw = False
        for name, value in changes.items():
            if name in pe.BRIDGED:
                if name in setters and live.get(name) != value:
                    setters[name](value)
            else:
                redraw = True
        if redraw:
            self._render()

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
                    self._place_title()
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
                self._apply_cbar(st)
            elif key == "legend":
                if (self._legend_items is not None and self._show_legend
                        and self._has_legend):
                    self._build_legend()
                    self._layout_side()
            self._relayout()
        except Exception:  # noqa: BLE001 - styling is cosmetic; never break a plot
            pass

    def _apply_cbar(self, st: dict) -> None:
        if self._cbar_spec is not None and self._cbar is not None:
            moved = st.get("orient", "right") != self._cbar_orient
            self._ensure_cbar()          # a new position: a new bar
            if moved:
                self._cbar.cmap = self._cbar_cm
                self._apply_visibility()
            self._cbar._update_colorbar()  # a new thickness
            self._set_cbar_ticks()       # number format / count
        if self._cbar_label is not None:
            self._cbar_label.text = st.get("text") or self._cbar_auto
            _style_text(self._cbar_label._text_visual, st)
        if self._cbar is not None:
            for tick in [*self._cbar.ticks, *self._cbar_extra]:
                _style_text(tick, st, "num_")
        self._layout_side()

    def _cbar_label_extent(self, st: dict) -> float:
        """The depth of the colour bar's name cell (0 with no name)."""
        if not (st.get("text") or self._cbar_auto):
            return 0.0
        return max(12.0, _CBAR_LABEL_W + 1.3 * (
            self._px(st["size"]) - self._px(9)))

    def _cbar_extent(self, st: dict) -> float:
        """How much room the colour bar's cell needs across the bar: the
        bar and its numbers (width beside the plot, height below it)."""
        try:
            bar = 2.0 * float(self._cbar._colorbar._halfdim[1])
        except Exception:  # noqa: BLE001
            bar = 22.0
        if st.get("thickness"):
            bar = float(st["thickness"])
        elif self._cbar_orient == "bottom":
            bar = _CBAR_BOTTOM_PX
        bar = min(max(bar, 4.0), 48.0)
        num_px = self._px(st["num_size"])
        if self._cbar_orient == "bottom":
            # The bar sits mid-cell with its numbers hanging below it: room
            # for them on both sides keeps them clear of the name.
            return max(24.0, bar + 2.0 * (num_px * 1.3 + 4.0))
        usual = max(48.0, _CBAR_W + 2.6 * (num_px - self._px(12)))
        if st.get("thickness") and not self._cbar_extra:
            usual = max(usual, bar / 0.8 + 8.0)
        labels = [str(t.text) for t in [*self._cbar.ticks, *self._cbar_extra]]
        if not self._cbar_extra and st.get("num_format", "auto") == "auto":
            return usual
        # Labelled along its length (or wide numbers): fit to the text. The
        # bar sits in the middle with the numbers on one side, hence twice
        # (the widest number + a gap) plus the bar.
        font = QFont(st.get("num_font") or pe.DEFAULT_FONT)
        font.setPixelSize(max(1, int(round(num_px))))
        fm = QFontMetricsF(font)
        widest = max((fm.horizontalAdvance(t) for t in labels), default=0.0)
        return max(usual, 2.0 * (widest + 12.0) + bar)

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
        line = st.get("line_color", _AXIS_TICK) if st.get("line") else _AXIS_LINE
        if str(axis.axis_color) != str(line):
            axis.axis_color = line
        if self._gridlines is not None:  # shared by both axes' editors
            rgba = QColor(st.get("grid_color", "#000000"))
            want = (rgba.redF(), rgba.greenF(), rgba.blueF(),
                    float(st.get("grid_opacity", 12)) / 100.0)
            if self._grid_rgba != want:
                self._grid_rgba = want
                self._gridlines._grid_color_fn["color"] = want
                self._gridlines.update()
        sig = (st.get("ticks"), st.get("format"), st.get("decimals"))
        if self._tick_sig.get(key) != sig:  # new ticks: lay out again
            self._tick_sig[key] = sig
            axis._need_update = True
            axis.update()
        # Bigger fonts need a deeper strip and the title pushed further out.
        d_title = self._px(st["size"]) - self._px(9)
        d_tick = self._px(st["tick_size"]) - self._px(8)
        if key == "xaxis":  # tick labels stack above the title
            axis.axis_label_margin = max(
                16.0, _AXIS_LABEL_MARGIN + d_tick + 0.5 * d_title)
            # A hidden axis gives its strip back to the plot.
            widget.height_max = (max(24.0, _XAXIS_H + d_tick + 1.3 * d_title)
                                 if widget.visible else 0)
        else:               # tick labels sit beside the (rotated) title
            self._fit_yaxis(force=True)

    def _own_ticks(self, key: str, axis) -> None:
        """Route an axis's tick placement through the element's settings
        (number of ticks, number format); VisPy's own when automatic."""
        ticker = axis.ticker
        own = ticker._get_tick_frac_labels
        ticker._get_tick_frac_labels = (
            lambda k=key, own=own, axis=axis: self._tick_fracs(k, own, axis))

    def _tick_fracs(self, key: str, own, axis):
        st = self._el_style.get(key, {})
        count = int(st.get("ticks") or 0)
        fmt, dec = st.get("format", "auto"), st.get("decimals", 2)
        if not count and fmt == "auto":
            return own()
        lo, hi = (float(v) for v in axis.domain)
        flip = hi < lo
        if flip:
            lo, hi = hi, lo
        span = hi - lo
        if count:
            major = np.asarray(pe.nice_ticks(lo, hi, max(2, count)), "float64")
            minor = np.zeros(0)
        else:
            major_frac, minor, _ = own()
            frac = np.asarray(major_frac, "float64")
            major = lo + (1.0 - frac if flip else frac) * span
            minor = np.asarray(minor, "float64")
        labels = [pe.format_number(float(v), fmt, dec) for v in major]
        if not count:
            return major_frac, minor, labels
        frac = (major - lo) / span if span else np.zeros_like(major)
        return (1.0 - frac if flip else frac), minor, labels

    def _fit_yaxis(self, force: bool = False) -> None:
        """Size the Y strip to the tick labels on screen, so the (rotated)
        title never sits on top of them — however long the numbers get and
        whatever the two font sizes are. Grows at once, shrinks lazily, so a
        pan that flips "-9.5" to "-10" doesn't make the plot jitter."""
        self._fit_pending = False
        widget = self._yaxis
        if widget is None:
            return
        if not widget.visible:  # hidden: its strip goes to the plot
            if widget.width_max != 0:
                widget.width_max = 0
                self._relayout()
            return
        force = force or not widget.width_max
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
            box = self._text_box(self.title, st, c.x(), c.y())
            align = st.get("align", "center")
            if align == "left":
                box.moveLeft(strip.left() + _TITLE_INSET - 6)
            elif align == "right":
                box.moveRight(strip.right() - _TITLE_INSET + 6)
            return box.intersected(strip.adjusted(0, -4, 0, 4))
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
        if key == "legend":
            return self._widget_rect(self._legend)
        if key == self._data_key:
            return self._widget_rect(self._view)
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

    def _element_at(self, pos, probe: bool = True) -> str | None:
        """The element under a canvas position. The data counts where its
        tooltip would show (a point, a bar, a curve, a violin) or, for a
        filled contour, anywhere on it. ``probe=False``: the hover has just
        run for ``pos``, so the tooltip already says."""
        if pos is None:
            return None
        pt = QPointF(float(pos[0]), float(pos[1]))
        for key in self._el_style:
            if key == self._data_key:
                continue
            rect = self._element_rect(key)
            if rect is not None and rect.contains(pt):
                return key
        key = self._data_key
        rect = self._element_rect(key)
        if rect is None or not rect.contains(pt):
            return None
        if key == "data_contour":
            return key
        if probe:
            from types import SimpleNamespace

            self._hover_data(SimpleNamespace(pos=pos, buttons=None))
        tip = self._tooltip
        return key if tip is not None and not tip.isHidden() else None

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
        self._place_cbar_ticks()
        self._on_view_resize()
        self._check_axes_layout()
        if self._selected is not None:
            QTimer.singleShot(0, self._sync_highlight)
        if self._yaxis is not None and not self._fit_pending:
            self._fit_pending = True  # the tick labels may have changed
            QTimer.singleShot(0, self._fit_yaxis)

    def _check_axes_layout(self) -> None:
        """Keep the axes' numbers lined up with the data. An axis re-reads the
        view only when the camera moves, so when the grid shifts the view or
        an axis strip (the Y strip refitting to its labels, the colour bar
        column changing width) the ticks would stay where they were."""
        if self._xaxis is None and self._yaxis is None:
            return
        try:
            sig = tuple(
                tuple(round(float(v), 1) for v in (*w.pos, *w.size))
                for w in (self._view, self._xaxis, self._yaxis) if w is not None)
        except Exception:  # noqa: BLE001
            return
        if sig != self._layout_sig:
            self._layout_sig = sig
            QTimer.singleShot(0, self._resync_axes)

    def _resync_axes(self) -> None:
        if self._canvas is None:
            return
        for axis in (self._xaxis, self._yaxis):
            if axis is not None and getattr(axis, "_linked_view", None) is not None:
                try:
                    axis._view_changed()
                except Exception:  # noqa: BLE001 - never break a plot over ticks
                    pass
        self._canvas.update()

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
        over = self._element_at(getattr(event, "pos", None),
                                probe=False) is not None
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
            # A contour fills its axes edge to edge, like a filled-contour
            # plot (with a sliver of room when the measured points are marked,
            # so the ones on the border are not cut in half).
            margin = 0.12
            if self.spec.is_contour:
                margin = 0.03 if self.spec.show_points else 0.0
            elif self.spec.is_curve:
                margin = 0.04  # a curve plot runs close to its axes
            self._view.camera.set_range(
                x=_span(lo[0], hi[0]), y=_span(lo[1], hi[1]), margin=margin)
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
            # The map colours KDE curves and many categories; scale and
            # range don't apply to them.
            "map_only": bool(self.spec.is_kde or self._legend_cmap),
            "has_points": self._has_points(),
            "cmin": cmin if cmin is not None else 0,
            "cmax": cmax if cmax is not None else 100,
        }

    def appearance(self) -> dict:
        """Full visual state, for cloning this plot into a detached window."""
        return {
            "cmap": self.cmap, "scale": self.scale, "crange": self.crange,
            "size": self._base_size, "symbol": self._symbol,
            "opacity": self._opacity, "axes": self._show_axes,
            "grid": self._show_grid, "bbox": self._show_bbox,
            "legend": self._show_legend, "title": self._show_title,
            "equal_axes": self._equal_axes, "title_text": self.title,
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
        self._equal_axes = a.get("equal_axes", self._equal_axes)
        if self._view is not None and self._is_spatial():
            self._view.camera.aspect = 1 if self._equal_axes else None
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
        self._hover_data(event)
        self._hover_cursor(event)  # after: the tooltip says if over the data

    def _hover_data(self, event) -> None:
        """The tooltip for the data under the pointer (hidden off it)."""
        if self.spec.is_bar or self.spec.is_hist or self.spec.is_cov:
            self._bar_hover(event)
            return
        if self.spec.is_curve:
            self._curve_hover(event)
            return
        if self.spec.is_violin:
            self._violin_hover(event)
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
        self._curve_data = None
        self._curve_lines = []
        self._curve_fill = self._ref_line = self._ref_label = None
        self._violin_data = None
        self._violin_mesh = self._violin_edges = self._violin_marks = None
        self._dist_df = self._dist_key = self._dist_data = None
        self._contour_img = None
        self._contour_pts = None
        self._contour_lines = None
        self._contour_data = None
        self._cbar_extra, self._cbar_extra_at = [], []
        self._axis_labels = []
        self._legend = None
        self._legend_parts = []
        self._bar_outline = None
        self._slots = {}
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
