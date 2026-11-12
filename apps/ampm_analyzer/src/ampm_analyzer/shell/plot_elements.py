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
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QSettings

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
    """One editable property. ``kind``: text | font | size | style | color.
    A ``style`` field is the bold + italic pair (keys ``bold`` / ``italic``,
    or ``<prefix>bold`` when ``name`` is ``<prefix>style``)."""

    name: str
    label: str
    kind: str
    group: str = ""


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


ELEMENTS: dict[str, Element] = {e.key: e for e in (
    # The title's text is the plot's name (kept on the tab, not in the style).
    Element("title", "Title", _text_fields(),
            _text_defaults(13, _TITLE_TEXT, text=False)),
    _axis2d("xaxis", "X axis"),
    _axis2d("yaxis", "Y axis"),
    _axis3d("xaxis3d", "X axis label", _AXIS3D[0]),
    _axis3d("yaxis3d", "Y axis label", _AXIS3D[1]),
    _axis3d("zaxis3d", "Z axis label", _AXIS3D[2]),
    Element("categories", "Category labels", _text_fields(text=False),
            _text_defaults(9, _AXIS_TEXT, text=False)),
    Element("cbar", "Colour bar",
            (*_text_fields("Label"),
             Field("num_font", "Font", "font", "Numbers"),
             Field("num_size", "Size", "size", "Numbers"),
             Field("num_color", "Colour", "color", "Numbers")),
            {**_text_defaults(9, _AXIS_TEXT),
             "num_font": DEFAULT_FONT, "num_size": 12, "num_color": "#000000"}),
)}

SIZE_RANGE = (5, 48)  # pt


def keys_for(spec) -> list[str]:
    """The elements a plot of this spec can have (whether each is on screen
    right now — a colour bar, category labels — is the tab's call)."""
    if spec.is_3d:
        return ["title", "xaxis3d", "yaxis3d", "zaxis3d", "cbar"]
    return ["title", "xaxis", "yaxis", "categories", "cbar"]


# -- styles: built-in <- saved default <- this plot's edits -----------------
_SETTINGS_GROUP = "plot_style"


def _settings() -> QSettings:
    return QSettings("AMPM", "AMPM Analyzer")


def _clean(key: str, style: dict) -> dict:
    """Keep only this element's known keys with sane values (a hand-edited or
    older saved style must not break a plot)."""
    el = ELEMENTS[key]
    out = {}
    for k in el.style_keys():
        if k == "text" or k not in style:
            continue
        v, d = style[k], el.defaults[k]
        if isinstance(d, bool):
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
KIND_DEFAULTS: dict[str, dict[str, dict]] = {
    "Contour": {"cbar": {"num_size": 9}},
}


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


def save_default(key: str, style: dict) -> None:
    """Make ``style`` (minus its text) the default for new plots. A style equal
    to the built-in look clears the saved default."""
    clean = _clean(key, style)
    built = builtin_style(key)
    diff = {k: v for k, v in clean.items() if built.get(k) != v}
    s = _settings()
    if diff:
        s.setValue(f"{_SETTINGS_GROUP}/{key}", json.dumps(diff))
    else:
        s.remove(f"{_SETTINGS_GROUP}/{key}")
