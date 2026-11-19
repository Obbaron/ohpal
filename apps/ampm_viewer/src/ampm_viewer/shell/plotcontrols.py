"""What a plot's toolbar offers: a declarative list of controls per plot view.

The toolbar no longer hard-codes its buttons. A plot reports the controls that
apply to it (``PlotTab.controls()``), each a ``Control`` described here, and the
toolbar renders whatever it is given. The plot also answers each control's
current value and applies changes by key (``control_value`` / ``set_control``).

This is what keeps future custom plot views cheap: a custom view declares its
own controls, or inherits its base view's (``controls_for(kind, base=...)``),
and both toolbars (main window and floating plot window) show them with no
toolbar code involved.

Pure description: no Qt, no plot objects.
"""

from __future__ import annotations

from dataclasses import dataclass

from .plotspec import (
    BAR, CONTOUR, COV_SUMMARY, HISTOGRAM, KDE, KDIST, LAYER_VIEWER,
    SCATTER_2D, SCATTER_3D, SINGLE_LAYER, VIOLIN,
)

# Toolbar groups, left to right; a separator falls between non-empty groups.
GROUPS = ("view", "scene", "options", "export")


@dataclass(frozen=True)
class Control:
    """One toolbar control.

    ``kind``:
      - ``toggle``  on/off (a checkable button)
      - ``action``  a one-shot button
      - ``choice``  a menu of exclusive values, the current one ticked
      - ``menu``    a menu of one-shot actions (no current value)
    ``choices`` are ``(value, label)`` pairs for ``choice`` / ``menu``.
    """

    key: str
    label: str            # the button's tooltip / the menu's title
    icon: str             # an ``icons.UI`` name
    kind: str = "toggle"
    group: str = "scene"
    choices: tuple = ()


# -- the controls every 2D / 3D plot view has -------------------------------
RESET_VIEW = Control("reset_view", "Reset view", "reset_view", "action", "view")
AXES = Control("axes", "Axes", "axes")
GRID = Control("grid", "Grid", "grid")
BBOX = Control("bbox", "BBox", "bbox")
LEGEND = Control("legend", "Legend", "legend")
TITLE = Control("title", "Title", "title")
SCREENSHOT = Control("screenshot", "Screenshot", "screenshot", "action", "export")
SAVE_LIBRARY = Control("save_library", "Save to plot library", "save_library",
                       "action", "export")

COMMON = (RESET_VIEW, AXES, GRID, BBOX, LEGEND, TITLE, SCREENSHOT, SAVE_LIBRARY)

# -- view options: only on the views they apply to ---------------------------
CAMERA_3D = Control(
    "camera", "3D view", "view3d", "menu", "view",
    (("top", "Top"), ("front", "Front"), ("side", "Side"), ("iso", "Iso")))
EQUAL_AXES = Control("equal_axes", "Equal axes (1:1)", "equal_axes", "toggle", "view")
LAYER_PREV = Control("layer_prev", "Previous layer", "layer_prev", "action", "view")
LAYER_NEXT = Control("layer_next", "Next layer", "layer_next", "action", "view")
VIOLIN_BOX = Control("show_box", "Quartile box and median", "violin_box",
                     "toggle", "options")
KDE_FILL = Control("fill", "Fill under curves", "kde_fill", "toggle", "options")
BANDWIDTH = Control("bandwidth", "Bandwidth", "bandwidth", "choice", "options",
                    (("scott", "Scott"), ("silverman", "Silverman")))
BIN_COUNTS = (10, 20, 30, 50, 100)
BINS = Control("bins", "Bins", "bins", "choice", "options",
               tuple((n, str(n)) for n in BIN_COUNTS))
SORT = Control("sort", "Sort bars", "sort", "choice", "options",
               (("name", "By name"), ("value", "By value")))
CONTOUR_POINTS = Control("show_points", "Measured points", "contour_points",
                         "toggle", "options")
CONTOUR_LINES = Control("show_lines", "Level lines", "contour_lines",
                        "toggle", "options")
KNEE_LINE = Control("show_ref", "Knee line", "knee_line", "toggle", "options")

VIEW_OPTIONS: dict[str, tuple] = {
    SCATTER_2D: (EQUAL_AXES,),
    SCATTER_3D: (CAMERA_3D,),
    LAYER_VIEWER: (EQUAL_AXES, LAYER_PREV, LAYER_NEXT),
    SINGLE_LAYER: (EQUAL_AXES,),
    BAR: (SORT,),
    COV_SUMMARY: (SORT,),
    HISTOGRAM: (BINS,),
    VIOLIN: (VIOLIN_BOX, BANDWIDTH),
    KDE: (KDE_FILL, BANDWIDTH),
    CONTOUR: (CONTOUR_POINTS, CONTOUR_LINES),
    KDIST: (KNEE_LINE,),
}


def controls_for(kind: str, *, base: str | None = None,
                 extra: tuple = ()) -> list[Control]:
    """Every control a view of ``kind`` can have, in toolbar order: the common
    ones, then its view options. A custom view passes the built-in view it is
    based on as ``base`` (inheriting its options) plus any ``extra`` controls
    of its own. Which of these are on screen right now is the plot's call
    (``PlotTab.controls()``): a legend needs something to show, a bounding box
    a 3D scene."""
    own = VIEW_OPTIONS.get(kind) or VIEW_OPTIONS.get(base or "", ())
    out = list(COMMON) + list(own) + [c for c in extra if c not in own]
    order = {g: i for i, g in enumerate(GROUPS)}
    return sorted(out, key=lambda c: order.get(c.group, len(GROUPS)))
