"""Context-swapping toolbar contents.

One QToolBar on the main window is rebuilt per active tab:
  * File  -> toolbar hidden (backstage has no toolbar)
  * Data  -> data toolset
  * Plot  -> plot toolset
Undo / redo / help are glyph (icon-only) buttons pinned to the right and are
re-appended on every rebuild so they persist across working tabs.

Everything here is inert — actions carry no connections. Discrete
actions/toggles/presets live on the toolbar; sliders live in the dock.
"""

from __future__ import annotations

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QComboBox,
    QLabel,
    QSizePolicy,
    QToolBar,
    QToolButton,
    QWidget,
)


# -- small builders ----------------------------------------------------
def _action(toolbar: QToolBar, text: str, *, checkable: bool = False) -> QAction:
    act = QAction(text, toolbar)
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


def _spacer() -> QWidget:
    w = QWidget()
    w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    return w


# -- right-hand persistent cluster ------------------------------------
def append_global(toolbar: QToolBar) -> dict[str, QToolButton]:
    """Expanding spacer, then undo / redo / help glyph buttons pinned right."""
    toolbar.addWidget(_spacer())
    glyphs = {"undo": "↶", "redo": "↷", "help": "?"}
    tips = {"undo": "Undo", "redo": "Redo", "help": "Help"}
    buttons: dict[str, QToolButton] = {}
    for key, glyph in glyphs.items():
        btn = QToolButton()
        btn.setText(glyph)
        btn.setToolTip(tips[key])
        btn.setProperty("class", "ToolbarGlyph")
        toolbar.addWidget(btn)
        buttons[key] = btn
    return buttons


# -- Data toolset ------------------------------------------------------
def populate_data(toolbar: QToolBar) -> None:
    # Columns
    _action(toolbar, "Add column")       # single button -> popup w/ mode spinner
    _action(toolbar, "Remove")
    _action(toolbar, "Rename")
    _action(toolbar, "Show/hide")
    toolbar.addSeparator()
    # View filters — query the DataStore cache down to a subregion/sub-range
    # (cheap; no rebuild). The store's own materialisation bounds live in the
    # backstage DataStore settings, not here.
    toolbar.addWidget(_muted("Layer"))
    layer = QComboBox()
    layer.addItems(["All layers", "Single…", "Range…"])
    layer.setFixedWidth(110)
    toolbar.addWidget(layer)
    _action(toolbar, "X/Y bounds")
    _action(toolbar, "Filter")
    _action(toolbar, "Clear filters")
    toolbar.addSeparator()
    # Plot
    _action(toolbar, "New plot")
    toolbar.addSeparator()
    # Export
    _action(toolbar, "Export to Excel")
    append_global(toolbar)


# -- Plot toolset ------------------------------------------------------
def populate_plot(toolbar: QToolBar) -> None:
    # View
    _action(toolbar, "Reset view")
    _combo(toolbar, "View", ["Iso", "Top", "Front", "Side"], width=80)
    _combo(toolbar, "Proj", ["Perspective", "Ortho"], width=110)
    toolbar.addSeparator()
    # Scene toggles (display on/off). Legend joins the scene toggles; colour-by,
    # colormap, scale and marker now live in the side panel. "Colour by" is a
    # plot input (a data column) and belongs to plot generation, not here.
    axes = _action(toolbar, "Axes", checkable=True)
    axes.setChecked(True)
    _action(toolbar, "Grid", checkable=True)
    _action(toolbar, "BBox", checkable=True)
    _action(toolbar, "Legend", checkable=True)
    toolbar.addSeparator()
    # Select
    _combo(toolbar, "Select", ["None", "Click", "Box", "Lasso"], width=80)
    _action(toolbar, "Clear")
    _action(toolbar, "Invert")
    toolbar.addSeparator()
    # Export
    _action(toolbar, "Screenshot")
    append_global(toolbar)
