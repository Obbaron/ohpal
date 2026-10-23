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
    QSpinBox,
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
def append_global(toolbar: QToolBar, *, on_settings=None) -> dict[str, QToolButton]:
    """Expanding spacer, then undo / redo / help / settings glyphs pinned right."""
    toolbar.addWidget(_spacer())
    glyphs = {"undo": "↶", "redo": "↷", "help": "?", "settings": "⚙"}
    tips = {"undo": "Undo", "redo": "Redo", "help": "Help", "settings": "Settings"}
    buttons: dict[str, QToolButton] = {}
    for key, glyph in glyphs.items():
        btn = QToolButton()
        btn.setText(glyph)
        btn.setToolTip(tips[key])
        btn.setProperty("class", "ToolbarGlyph")
        toolbar.addWidget(btn)
        buttons[key] = btn
    if on_settings is not None:
        buttons["settings"].clicked.connect(on_settings)
    return buttons


# -- Data toolset ------------------------------------------------------
def populate_data(toolbar: QToolBar, *, on_new_plot=None, on_settings=None) -> None:
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
    new_plot = _action(toolbar, "New plot")
    if on_new_plot is not None:
        new_plot.triggered.connect(on_new_plot)
    toolbar.addSeparator()
    # Columns
    _action(toolbar, "Add column")       # single button -> popup w/ mode spinner
    _action(toolbar, "Remove")
    _action(toolbar, "Show/hide")
    toolbar.addSeparator()
    # View filters on the cache (cheap; no rebuild).
    _action(toolbar, "X/Y bounds")
    _action(toolbar, "Filter")
    _action(toolbar, "Clear filters")
    toolbar.addSeparator()
    # Export
    _action(toolbar, "Export to Excel")
    append_global(toolbar, on_settings=on_settings)


# -- Plot toolset ------------------------------------------------------
def populate_plot(toolbar: QToolBar, *, on_settings=None) -> None:
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
    append_global(toolbar, on_settings=on_settings)
