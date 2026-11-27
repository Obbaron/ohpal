"""Editable plot elements: what can be selected on a plot, the properties each
one exposes, the fonts on offer, and the saved "default for new plots" styles.

Pure description + storage — no VisPy objects here. ``PlotTab`` owns the live
chrome and applies a style to it; the side panel builds its controls from the
``Field`` list, so a new editable element is a new ``Element`` entry, not new
panel code.

A style is a flat dict per element (``font``, ``size``, ``bold``, ``italic``,
``color``, …). ``text`` is the one per-plot field: "" means automatic (the
column's name), and it is never part of a saved default.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QSettings

from .settings import app_settings

# -- fonts ---------------------------------------------------------------
# Display name -> VisPy face. VisPy loads a face from "<face>-Regular.ttf",
# "-Bold", "-Italic", "-BoldItalic" in a registered folder. Open Sans ships
# inside VisPy; the Liberation families (SIL OFL 1.1, metric-compatible with
# Arial / Times New Roman / Courier New) are bundled under assets/fonts.
FONTS: dict[str, str] = {
    "Open Sans": "OpenSans",
    "Liberation Sans": "LiberationSans",
    "Liberation Serif": "LiberationSerif",
    "Liberation Mono": "LiberationMono",
}
DEFAULT_FONT = "Open Sans"
_FONT_DIR = Path(__file__).parent / "assets" / "fonts"
_fonts_ready = False


def face(font: str | None) -> str:
    """The VisPy face for a display font name (unknown names fall back)."""
    return FONTS.get(font or "", FONTS[DEFAULT_FONT])


def ensure_fonts() -> None:
    """Make the bundled fonts available to VisPy (which draws the plot text)
    and to Qt (which measures it for hit-testing and previews it in the font
    picker). Safe to call repeatedly; needs a QGuiApplication."""
    global _fonts_ready
    if _fonts_ready:
        return
    _fonts_ready = True
    dirs = [_FONT_DIR]
    try:
        import vispy.util.fonts as vfonts
        from vispy.util.fonts._vispy_fonts import register_vispy_font

        for name in FONTS.values():
            if name != "OpenSans":
                register_vispy_font(_FONT_DIR, name, False, False)
        dirs.append(Path(vfonts.__file__).parent / "data")  # Open Sans
    except Exception:  # noqa: BLE001 - no VisPy: the plot tab shows a placeholder
        pass
    try:
        from PyQt6.QtGui import QFontDatabase

        for d in dirs:
            for ttf in sorted(d.glob("*.ttf")):
                QFontDatabase.addApplicationFont(str(ttf))
    except Exception:  # noqa: BLE001 - metrics fall back to the default font
        pass


# -- elements --------------------------------------------------------------
@dataclass(frozen=True)
class Field:
    """One editable property. ``kind``:

    - ``text``    free text ("" = automatic)
    - ``font``    one of ``FONTS``
    - ``size``    a font size in pt (``SIZE_RANGE``)
    - ``style``   the bold + italic pair (keys ``bold`` / ``italic``, or
                  ``<prefix>bold`` when ``name`` is ``<prefix>style``)
    - ``color``   a colour
    - ``choice``  one of ``options`` (``(value, label)`` pairs)
    - ``int``     a whole number in ``lo``..``hi`` (``special``: what ``lo``
                  means, e.g. "Auto"; ``suffix``: its unit)
    - ``check``   on / off
    - ``number``  a decimal number, or None (``special``: what None shows,
                  e.g. "Auto")
    """

    name: str
    label: str
    kind: str
    group: str = ""
    options: tuple = ()
    lo: int = 0
    hi: int = 0
    suffix: str = ""
    special: str = ""


@dataclass(frozen=True)
class Element:
    key: str
    label: str
    fields: tuple[Field, ...]
    defaults: dict

    def style_keys(self) -> list[str]:
        """Every key of this element's style dict, in field order."""
        keys: list[str] = []
        for f in self.fields:
            if f.kind == "style":
                prefix = f.name[: -len("style")]
                keys += [prefix + "bold", prefix + "italic"]
            else:
                keys.append(f.name)
        return keys


_TITLE_TEXT = "#2a2f3a"
_AXIS_TEXT = "#5a6472"
_AXIS3D = ("#cc1f1f", "#1a8c1f", "#1f4dd9")  # x, y, z label colours


def _text_fields(group: str = "", text: bool = True) -> tuple[Field, ...]:
    out = [Field("text", "Text", "text", group)] if text else []
    return (*out,
            Field("font", "Font", "font", group),
            Field("size", "Size", "size", group),
            Field("style", "Style", "style", group),
            Field("color", "Colour", "color", group))


def _text_defaults(size: float, color: str, *, bold: bool = False,
                   text: bool = True) -> dict:
    d = {"font": DEFAULT_FONT, "size": size, "bold": bold, "italic": False,
         "color": color}
    if text:
        d["text"] = ""
    return d


def _axis2d(key: str, label: str) -> Element:
    return Element(
        key, label,
        (*_text_fields("Axis title"),
         Field("tick_font", "Font", "font", "Tick labels"),
         Field("tick_size", "Size", "size", "Tick labels"),
         Field("tick_color", "Colour", "color", "Tick labels")),
        {**_text_defaults(9, _AXIS_TEXT),
         "tick_font": DEFAULT_FONT, "tick_size": 8, "tick_color": _AXIS_TEXT},
    )


def _axis3d(key: str, label: str, color: str) -> Element:
    return Element(key, label, _text_fields(),
                   _text_defaults(10, color, bold=True))


# -- number formats (axis ticks, colour-bar numbers) ------------------------
FORMATS = (("auto", "Automatic"), ("fixed", "Fixed decimals"),
           ("sci", "Scientific"))


def _tick_fields(group: str, prefix: str = "") -> tuple[Field, ...]:
    return (
        Field(prefix + "ticks", "Number of ticks", "int", group, lo=0, hi=12,
              special="Auto"),
        Field(prefix + "format", "Format", "choice", group, options=FORMATS),
        Field(prefix + "decimals", "Decimals", "int", group, lo=0, hi=8),
    )


def _tick_defaults(prefix: str = "") -> dict:
    return {prefix + "ticks": 0, prefix + "format": "auto",
            prefix + "decimals": 2}


def format_number(value: float, fmt: str, decimals: int) -> str:
    """A tick / colour-bar number in the chosen format."""
    if fmt == "fixed":
        return f"{value:.{int(decimals)}f}"
    if fmt == "sci":
        return f"{value:.{int(decimals)}e}"
    return f"{value:g}"


def nice_ticks(lo: float, hi: float, count: int) -> list[float]:
    """About ``count`` round values spanning ``lo``..``hi`` (1, 2, 2.5, 5 x
    10^k steps), only those inside the range."""
    import math

    if not (math.isfinite(lo) and math.isfinite(hi)) or hi <= lo or count < 2:
        return []
    raw = (hi - lo) / (count - 1)
    mag = 10 ** math.floor(math.log10(raw))

    def ticks(step):
        first = math.ceil(lo / step - 1e-9) * step
        out, i = [], 0
        while first + i * step <= hi + step * 1e-9 and len(out) < 60:
            v = first + i * step
            out.append(0.0 if abs(v) < step * 1e-9 else v)
            i += 1
        return out

    # The round step whose ticks inside the range come closest to ``count``
    # (more rather than fewer on a tie).
    steps = [m * mag * f for f in (0.1, 1, 10) for m in (1, 2, 2.5, 5)]
    best = min((ticks(st) for st in steps),
               key=lambda t: (abs(len(t) - count), -len(t)))
    return best


_GRID = "#000000"
# Category label angles: Automatic turns them only as far as they need.
_CORNERS = (("top_left", "Top left"), ("top_right", "Top right"),
            ("bottom_left", "Bottom left"), ("bottom_right", "Bottom right"))
ANGLES = (("auto", "Automatic"), ("0", "Horizontal"), ("45", "45\u00b0"),
          ("90", "Vertical"))
_PLACES = (("outside", "Outside, right"), ("top_right", "Inside, top right"),
           ("top_left", "Inside, top left"),
           ("bottom_right", "Inside, bottom right"),
           ("bottom_left", "Inside, bottom left"))
# Where a point's label sits, beside its marker.
LABEL_SIDES = (("right", "Right"), ("left", "Left"), ("above", "Above"),
               ("below", "Below"), ("above_right", "Above right"))


def _axis2d_full(key: str, label: str) -> Element:
    """A 2D axis: its title and tick labels (stage 1), the ticks' number and
    format, its line, and the gridlines (shared by both axes)."""
    base = _axis2d(key, label)
    return Element(
        key, label,
        (*base.fields,
         Field("min", "Minimum", "number", "Scale", special="Auto"),
         Field("max", "Maximum", "number", "Scale", special="Auto"),
         Field("log", "Log scale", "check", "Scale"),
         *_tick_fields("Ticks"),
         Field("line", "Show the axis line", "check", "Axis line"),
         Field("line_color", "Colour", "color", "Axis line"),
         Field("grid_color", "Colour", "color", "Gridlines (both axes)"),
         Field("grid_opacity", "Opacity", "int", "Gridlines (both axes)",
               lo=0, hi=100, suffix=" %")),
        {**base.defaults, **_tick_defaults(), "min": None, "max": None,
         "log": False, "line": False,
         "line_color": "#7a8290", "grid_color": _GRID, "grid_opacity": 12},
    )


# -- the data, one element per kind of drawing ------------------------------
def _cmap_field() -> Field:
    from .plotdata import COLORMAP_NAMES

    return Field("cmap", "Colour map", "choice", "Colour",
                 options=tuple((n, n) for n in COLORMAP_NAMES))


def _data_elements() -> list[Element]:
    from .plotdata import DEFAULT_COLORMAP

    cmap = _cmap_field()
    symbols = tuple((s, s.capitalize())
                    for s in ("disc", "square", "ring", "cross"))
    return [
        Element("data_points", "Points", (
            Field("symbol", "Marker", "choice", "Points", options=symbols),
            Field("size", "Size", "int", "Points", lo=1, hi=20, suffix=" px"),
            Field("opacity", "Opacity", "int", "Points", lo=0, hi=100,
                  suffix=" %"),
            cmap,
            Field("scale", "Scale", "choice", "Colour",
                  options=(("linear", "Linear"), ("log", "Log"))),
        ), {"symbol": "disc", "size": 3, "opacity": 100,
            "cmap": DEFAULT_COLORMAP, "scale": "linear"}),
        Element("data_bars", "Bars", (
            Field("bar_width", "Width", "int", "Bars", lo=20, hi=100,
                  suffix=" %"),
            Field("outline", "Outline", "check", "Bars"),
            Field("outline_color", "Outline colour", "color", "Bars"),
            cmap,
        ), {"bar_width": 80, "outline": False, "outline_color": "#2a2f3a",
            "cmap": DEFAULT_COLORMAP}),
        Element("data_curves", "Curves", (
            Field("line_width", "Line width", "int", "Curves", lo=1, hi=8,
                  suffix=" px"),
            Field("fill_opacity", "Fill opacity", "int", "Curves", lo=0,
                  hi=60, suffix=" %", special="Auto"),
            cmap,
        ), {"line_width": 2, "fill_opacity": 0, "cmap": DEFAULT_COLORMAP}),
        Element("data_kdist", "Curve", (
            Field("line_color", "Colour", "color", "Curve"),
            Field("line_width", "Line width", "int", "Curve", lo=1, hi=8,
                  suffix=" px"),
            Field("guide_color", "Knee line colour", "color", "Curve"),
        ), {"line_color": "#2966c7", "line_width": 2,
            "guide_color": "#cc3333"}),
        Element("data_violins", "Violins", (
            Field("fill_opacity", "Fill opacity", "int", "Violins", lo=10,
                  hi=100, suffix=" %"),
            Field("outline_color", "Outline colour", "color", "Violins"),
            cmap,
        ), {"fill_opacity": 85, "outline_color": "#292e38",
            "cmap": DEFAULT_COLORMAP}),
        Element("data_contour", "Filled contours", (
            Field("line_color", "Colour", "color", "Level lines"),
            Field("line_opacity", "Opacity", "int", "Level lines", lo=0,
                  hi=100, suffix=" %"),
            Field("line_width", "Width", "int", "Level lines", lo=1, hi=4,
                  suffix=" px"),
            Field("point_size", "Size", "int", "Measured points", lo=2,
                  hi=14, suffix=" px"),
            cmap,
        ), {"line_color": "#000000", "line_opacity": 16, "line_width": 1,
            "point_size": 6, "cmap": "viridis"}),
    ]


# Data fields that are the plot's own settings (shared with the side panel's
# Points / Colour controls), not part of the element's stored style.
BRIDGED = {"symbol", "size", "opacity", "cmap", "scale"}


def data_key(spec) -> str:
    """The data element of a plot of this spec."""
    if spec.is_bar or spec.is_hist or spec.is_cov:
        return "data_bars"
    if spec.is_kde:
        return "data_curves"
    if spec.is_kdist:
        return "data_kdist"
    if spec.is_violin:
        return "data_violins"
    if spec.is_contour:
        return "data_contour"
    return "data_points"


ELEMENTS: dict[str, Element] = {e.key: e for e in (
    # The title's text is the plot's name (kept on the tab, not in the style).
    Element("title", "Title",
            (*_text_fields(),
             Field("align", "Alignment", "choice", options=(
                 ("center", "Centre"), ("left", "Left"), ("right", "Right")))),
            {**_text_defaults(13, _TITLE_TEXT, text=False), "align": "center"}),
    _axis2d_full("xaxis", "X axis"),
    _axis2d_full("yaxis", "Y axis"),
    _axis3d("xaxis3d", "X axis label", _AXIS3D[0]),
    _axis3d("yaxis3d", "Y axis label", _AXIS3D[1]),
    _axis3d("zaxis3d", "Z axis label", _AXIS3D[2]),
    # The names under a bar / CoV / violin chart, on its x axis. Too many to
    # sit side by side: turned (Automatic) and, if still too many, only every
    # 2nd, 3rd... is shown.
    Element("categories", "Category labels",
            (*_text_fields(text=False),
             Field("angle", "Angle", "choice", "Layout", options=ANGLES)),
            {**_text_defaults(9, _AXIS_TEXT, text=False), "angle": "auto"}),
    Element("cbar", "Colour bar",
            (*_text_fields("Label"),
             Field("num_font", "Font", "font", "Numbers"),
             Field("num_size", "Size", "size", "Numbers"),
             Field("num_color", "Colour", "color", "Numbers"),
             *_tick_fields("Numbers", "num_"),
             Field("orient", "Position", "choice", "Layout", options=(
                 ("right", "Right of the plot"), ("bottom", "Below the plot"))),
             Field("gap", "Gap to the plot", "int", "Layout", lo=0, hi=80,
                   suffix=" px"),
             Field("thickness", "Bar thickness", "int", "Layout", lo=0, hi=48,
                   suffix=" px", special="Auto")),
            {**_text_defaults(9, _AXIS_TEXT),
             "num_font": DEFAULT_FONT, "num_size": 12, "num_color": "#000000",
             **_tick_defaults("num_"), "orient": "right", "gap": 0,
             "thickness": 0}),
    # A legend of groups (KDE curves, a scatter coloured by a text column).
    Element("legend", "Legend",
            (*_text_fields("Title"),
             Field("name_font", "Font", "font", "Names"),
             Field("name_size", "Size", "size", "Names"),
             Field("name_color", "Colour", "color", "Names"),
             Field("place", "Position", "choice", "Box", options=_PLACES),
             Field("frame", "Frame", "check", "Box"),
             Field("frame_color", "Frame colour", "color", "Box")),
            {**_text_defaults(9, _TITLE_TEXT, bold=True),
             "name_font": DEFAULT_FONT, "name_size": 9,
             "name_color": _AXIS_TEXT, "place": "outside", "frame": True,
             "frame_color": "#b8bec8"}),
    # The trend line of a 2D scatter / Mean ± SD and its label (a corner of
    # the plot): the line's equation, R squared, p and n.
    Element("fit", "Trend line",
            (*_text_fields("Label", text=False),
             Field("place", "Position", "choice", "Label", options=_CORNERS),
             Field("equation", "Equation", "check", "Shows"),
             Field("r2", "R\u00b2", "check", "Shows"),
             Field("p", "p-value", "check", "Shows"),
             Field("n", "Number of points", "check", "Shows"),
             Field("line_color", "Colour", "color", "Line"),
             Field("line_width", "Width", "int", "Line", lo=1, hi=6,
                   suffix=" px"),
             Field("dashed", "Dashed", "check", "Line")),
            {**_text_defaults(9, _TITLE_TEXT, text=False), "place": "top_left",
             "equation": True, "r2": True, "p": True, "n": False,
             "line_color": "#7f7f7f", "line_width": 2, "dashed": True}),
    # A text by each point of a 2D scatter / Mean ± SD ("Label points").
    Element("labels", "Point labels",
            (*_text_fields("Labels", text=False),
             Field("side", "Position", "choice", "Labels", options=LABEL_SIDES)),
            {**_text_defaults(8, _AXIS_TEXT, text=False), "side": "right"}),
    *_data_elements(),
)}

SIZE_RANGE = (5, 48)  # pt


def keys_for(spec) -> list[str]:
    """The elements a plot of this spec can have (whether each is on screen
    right now, such as a colour bar or category labels, is the tab's call).
    The data comes last, so the chrome drawn over it wins a click."""
    if spec.is_3d:
        return ["title", "xaxis3d", "yaxis3d", "zaxis3d", "cbar", "legend",
                data_key(spec)]
    fit = ["fit"] if getattr(spec, "can_fit", False) else []
    labels = ["labels"] if getattr(spec, "can_fit", False) else []
    return ["title", "xaxis", "yaxis", "categories", "cbar", "legend", *fit,
            *labels, data_key(spec)]


def style_kind(spec) -> str:
    """The kind whose built-in look a plot takes (``KIND_DEFAULTS``): its own,
    or, for a scatter of one point per group, that variant's."""
    return PER_GROUP_KIND if getattr(spec, "is_per", False) else spec.kind


# -- styles: built-in <- saved default <- this plot's edits -----------------
_SETTINGS_GROUP = "plot_style"


def _settings() -> QSettings:
    return app_settings()


def _clean(key: str, style: dict) -> dict:
    """Keep only this element's known keys with sane values (a hand-edited or
    older saved style must not break a plot)."""
    el = ELEMENTS[key]
    fields = {f.name: f for f in el.fields}
    out = {}
    for k in el.style_keys():
        if k == "text" or k not in style:
            continue
        v, d = style[k], el.defaults[k]
        f = fields.get(k)
        kind = f.kind if f is not None else ""
        if kind == "choice":
            if v in {o for o, _ in f.options}:
                out[k] = v
        elif kind == "number":
            try:
                num = None if v is None or v == "" else float(v)
            except (TypeError, ValueError):
                continue
            out[k] = num if num is None or math.isfinite(num) else None
        elif kind == "int":
            try:
                out[k] = int(min(f.hi, max(f.lo, round(float(v)))))
            except (TypeError, ValueError):
                continue
        elif isinstance(d, bool):
            out[k] = bool(v)
        elif isinstance(d, (int, float)):
            try:
                out[k] = min(SIZE_RANGE[1], max(SIZE_RANGE[0], float(v)))
            except (TypeError, ValueError):
                continue
        elif k.endswith("font"):
            if v in FONTS:
                out[k] = v
        elif isinstance(v, str) and v:
            out[k] = v
    return out


# Built-in looks that differ for one kind of plot. A contour plot's colour bar
# is labelled along its whole length, so its numbers start smaller.
# A category axis shows its rule (a numeric one blends into the background).
_CATEGORY_AXIS = {"xaxis": {"line": True, "line_color": "#8a94a6"}}
# A 2D scatter of one point per group looks like Mean ± SD (a few big points).
PER_GROUP_KIND = "2D Scatter, one point per group"
KIND_DEFAULTS: dict[str, dict[str, dict]] = {
    "Contour": {"cbar": {"num_size": 9}},
    "Bar": _CATEGORY_AXIS, "CoV Summary": _CATEGORY_AXIS, "Violin": _CATEGORY_AXIS,
    "Histogram": {"data_bars": {"bar_width": 100}},   # bins touch
    "Mean ± SD": {"data_points": {"size": 8},           # a few points, visible
                  "labels": {"side": "above_right"}},  # (clear of the bars)
    PER_GROUP_KIND: {"data_points": {"size": 8}},       # (as Mean ± SD)
}
# Style keys that belong to one plot, never a default for new plots: an
# axis's set range is about that plot's data.
PER_PLOT = {"min", "max"}


def builtin_style(key: str, kind: str | None = None) -> dict:
    """The built-in look of an element (``kind``: the plot's kind, for the
    few looks that depend on it)."""
    return {**ELEMENTS[key].defaults,
            **KIND_DEFAULTS.get(kind or "", {}).get(key, {})}


def saved_default(key: str) -> dict:
    """The user's saved default for ``key`` ({} when none)."""
    raw = _settings().value(f"{_SETTINGS_GROUP}/{key}", "")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return _clean(key, data) if isinstance(data, dict) else {}


def default_style(key: str, kind: str | None = None) -> dict:
    """What a new plot starts from: the built-in look with the saved default
    on top."""
    return {**builtin_style(key, kind), **saved_default(key)}


def saved_defaults() -> list[str]:
    """The elements with a saved default style."""
    s = _settings()
    s.beginGroup(_SETTINGS_GROUP)
    try:
        return [k for k in s.childKeys() if k in ELEMENTS]
    finally:
        s.endGroup()


def clear_defaults() -> None:
    """Forget every saved default style: new plots get the built-in look."""
    _settings().remove(_SETTINGS_GROUP)


def save_default(key: str, style: dict, kind: str | None = None) -> None:
    """Make ``style`` (minus its text) the default for new plots. A style equal
    to the built-in look (of a ``kind`` plot) clears the saved default."""
    clean = {k: v for k, v in _clean(key, style).items() if k not in PER_PLOT}
    built = builtin_style(key, kind)
    diff = {k: v for k, v in clean.items() if built.get(k) != v}
    s = _settings()
    if diff:
        s.setValue(f"{_SETTINGS_GROUP}/{key}", json.dumps(diff))
    else:
        s.remove(f"{_SETTINGS_GROUP}/{key}")
