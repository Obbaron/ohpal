"""Context-swapping toolbar contents.

One QToolBar on the main window is rebuilt per active tab:
  * File  -> toolbar hidden (backstage has no toolbar)
  * Data  -> data toolset
  * Plot  -> plot toolset

The global cluster (undo / redo / help / settings) is NOT here — it lives in
the tab row (see window.py) so it stays reachable on every tab, including File
where this toolbar is hidden.

Everything here is inert — actions carry no connections. Discrete
actions/toggles/presets live on the toolbar; sliders live in the dock.
"""

from __future__ import annotations

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QComboBox,
    QLabel,
    QSpinBox,
    QToolBar,
)

from . import icons


# -- small builders ----------------------------------------------------
def _action(
    toolbar: QToolBar, text: str, icon: str, color: str, *, checkable: bool = False
) -> QAction:
    act = QAction(text, toolbar)
    act.setToolTip(text)  # icon-only toolbar -> text becomes the tooltip
    act.setIcon(icons.ui(icon, color))
    act.setCheckable(checkable)
    toolbar.addAction(act)
    return act


def _combo(toolbar: QToolBar, label: str, items: list[str], width: int = 110) -> QComboBox:
    toolbar.addWidget(_muted(label))
    cb = QComboBox()
    cb.addItems(items)
    cb.setFixedWidth(width)
    toolbar.addWidget(cb)
    return cb


def _muted(text: str) -> QLabel:
    lab = QLabel(text)
    return lab


# -- Data toolset ------------------------------------------------------
def populate_data(toolbar: QToolBar, *, color: str, on_new_plot=None) -> None:
    # Layer (a single layer number) — first control. Each layer is its own
    # file; this is a view filter on the cache, not a store-materialisation
    # bound (those live in the backstage DataStore settings).
    toolbar.addWidget(_muted("Layer"))
    layer = QSpinBox()
    layer.setRange(1, 100_000)
    layer.setValue(1)
    layer.setFixedWidth(80)
    toolbar.addWidget(layer)
    # New plot — second control. (Will open plot setup once wired.)
    new_plot = _action(toolbar, "New plot", "new_plot", color)
    if on_new_plot is not None:
        new_plot.triggered.connect(on_new_plot)
    toolbar.addSeparator()
    # Columns
    _action(toolbar, "Add column", "add_column", color)  # popup w/ mode spinner
    _action(toolbar, "Remove", "remove_column", color)
    _action(toolbar, "Show/hide", "show_hide", color)
    toolbar.addSeparator()
    # View filters on the cache (cheap; no rebuild).
    _action(toolbar, "X/Y bounds", "xy_bounds", color)
    _action(toolbar, "Filter", "filter", color)
    _action(toolbar, "Clear filters", "clear_filters", color)
    toolbar.addSeparator()
    # Export
    _action(toolbar, "Export to Excel", "export_excel", color)


# -- Plot toolset ------------------------------------------------------
def populate_plot(toolbar: QToolBar, *, color: str) -> None:
    # View
    _action(toolbar, "Reset view", "reset_view", color)
    _combo(toolbar, "View", ["Iso", "Top", "Front", "Side"], width=80)
    _combo(toolbar, "Proj", ["Perspective", "Ortho"], width=110)
    toolbar.addSeparator()
    # Scene toggles (display on/off). Legend joins the scene toggles; colour-by,
    # colormap, scale and marker now live in the side panel. "Colour by" is a
    # plot input (a data column) and belongs to plot generation, not here.
    axes = _action(toolbar, "Axes", "axes", color, checkable=True)
    axes.setChecked(True)
    _action(toolbar, "Grid", "grid", color, checkable=True)
    _action(toolbar, "BBox", "bbox", color, checkable=True)
    _action(toolbar, "Legend", "legend", color, checkable=True)
    toolbar.addSeparator()
    # Select
    _combo(toolbar, "Select", ["None", "Click", "Box", "Lasso"], width=80)
    _action(toolbar, "Clear", "clear_sel", color)
    _action(toolbar, "Invert", "invert_sel", color)
    toolbar.addSeparator()
    # Export
    _action(toolbar, "Screenshot", "screenshot", color)
