"""Icon registry (Carbon icons, bundled as SVG).

Icons come from IBM's Carbon set (Apache-2.0, see assets/icons/carbon/LICENSE),
bundled as SVG under ``assets/icons/``. Each SVG is a single-colour path with no
baked fill, so ``icon(stem, color)`` renders it tinted to any colour — which is
how icons follow the light/dark palette (the window re-tints on theme switch).

Three groups:
- ``UI``        — semantic name -> Carbon stem for toolbar/chrome actions.
- ``PLOT_TYPE`` — view NAME -> stem for the nine built-in plot types.
- the full Carbon **chart family** is bundled too (not just the nine), so
  user-defined custom charts can be given an icon — pick one explicitly, or let
  ``auto_match(name)`` guess from the chart's name. Fallback is ``chart--custom``.

Custom-derived icons live under ``custom/`` and are referenced as
``"custom/<name>"`` (e.g. the single-layer icon derived from Carbon ``layers``).
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QImage, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

_ICON_DIR = Path(__file__).parent / "assets" / "icons"
_cache: dict[tuple[str, str, int], QIcon] = {}

# -- semantic UI icons -------------------------------------------------
UI = {
    "undo": "undo", "redo": "redo", "help": "help", "settings": "settings",
    # backstage
    "load_packet": "data--base", "create_excel": "XLS", "open": "folder",
    "export": "export", "info": "information", "close": "close",
    "datastore": "datastore", "recent": "recently-viewed",
    "favourites": "favorite", "shared": "share", "search": "search",
    # data toolbar
    "sidebar": "side-panel--open", "sidebar_close": "side-panel--close",
    "layer": "layers", "new_plot": "chart--custom",
    "rename_column": "edit",
    "add_column": "column--insert", "remove_column": "column--delete",
    "show_hide": "view", "xy_bounds": "crop",
    # load-recipe steps (applied on top of the query)
    "mask": "shape--intersect", "assign_parts": "assembly--cluster",
    "correction": "calibrate",
    # filters
    "filter": "filter", "remove_filter": "filter--remove",
    "reset_filter": "filter--reset", "clear_filters": "filter--reset",
    "export_excel": "XLS",
    # plot toolbar
    "reset_view": "fit-to-screen", "axes": "x-axis", "grid": "grid",
    "bbox": "cube", "legend": "legend", "select": "select--01",
    "clear_sel": "close", "invert_sel": "select--02",
    "sel_box": "select--window", "sel_lasso": "lasso", "screenshot": "camera",
    # panel
    "marker": "dot-mark", "colormap": "color-palette",
    "scale": "chart--logistic-regression", "opacity": "opacity",
}

# -- the nine built-in plot types (view NAME -> stem) ------------------
PLOT_TYPE = {
    "3D Scatter": "chart--3D",
    "2D Scatter": "chart--scatter",
    "Bar": "chart--bar",
    "K-Distance Curve": "chart--line",
    "KDE": "chart--area",
    "Contour": "contour-finding",
    "CoV Summary": "chart--histogram",
    "Layer Viewer": "layers",
    "Single Layer": "custom/layer-single",
}

# Keyword -> stem for guessing a custom chart's icon (first match wins).
_AUTO = [
    (("3d", "three-d"), "chart--3D"),
    (("scatter-matrix", "splom"), "scatter-matrix"),
    (("scatter",), "chart--scatter"),
    (("violin",), "chart--violin-plot"),
    (("box",), "box-plot"),
    (("qq", "quantile"), "qq-plot"),
    (("contour",), "contour-finding"),
    (("hist", "kde", "density", "distribution"), "chart--histogram"),
    (("area",), "chart--area"),
    (("bar", "column"), "chart--bar"),
    (("line", "curve", "trend"), "chart--line"),
    (("pie", "donut"), "chart--pie"),
    (("radar", "spider"), "chart--radar"),
    (("heat", "treemap"), "chart--treemap"),
    (("network", "graph", "relationship"), "chart--network"),
    (("waterfall",), "chart--waterfall"),
    (("bubble",), "chart--bubble"),
    (("stem", "leaf"), "stem-leaf-plot"),
    (("time", "series"), "time-plot"),
    (("layer",), "layers"),
]


def auto_match(name: str) -> str:
    low = name.lower()
    for keys, stem in _AUTO:
        if any(k in low for k in keys):
            return stem
    return "chart--custom"


def list_chart_icons() -> list[str]:
    """All bundled chart/plot stems, for a custom-chart picker."""
    out = []
    for p in sorted((_ICON_DIR / "carbon").glob("*.svg")):
        stem = p.stem
        if stem.startswith("chart--") or stem.endswith("-plot") or "contour" in stem:
            out.append(stem)
    return out


# -- rendering ---------------------------------------------------------
def _svg_path(stem: str) -> Path:
    if stem.startswith("custom/"):
        return _ICON_DIR / "custom" / (stem.split("/", 1)[1] + ".svg")
    return _ICON_DIR / "carbon" / (stem + ".svg")


def icon(stem: str, color: str, px: int = 18) -> QIcon:
    """A QIcon of the given Carbon stem, tinted to ``color`` (hex)."""
    key = (stem, color, px)
    hit = _cache.get(key)
    if hit is not None:
        return hit
    path = _svg_path(stem)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return QIcon()  # missing stem -> empty icon rather than crash
    text = text.replace("<svg ", f'<svg fill="{color}" ', 1)
    renderer = QSvgRenderer(bytearray(text, "utf-8"))
    dpr = 2
    img = QImage(px * dpr, px * dpr, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    renderer.render(painter)
    painter.end()
    pixmap = QPixmap.fromImage(img)
    pixmap.setDevicePixelRatio(dpr)
    result = QIcon(pixmap)
    _cache[key] = result
    return result


def ui(name: str, color: str, px: int = 18) -> QIcon:
    """Icon for a semantic UI name (empty icon if unknown)."""
    stem = UI.get(name)
    return icon(stem, color, px) if stem else QIcon()


def for_view(view_name: str, color: str, px: int = 18) -> QIcon:
    """Icon for a plot type by its view NAME (auto-guessed if not built-in)."""
    stem = PLOT_TYPE.get(view_name) or auto_match(view_name)
    return icon(stem, color, px)


def clear_cache() -> None:
    _cache.clear()
