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
    QMenu,
    QSpinBox,
    QToolBar,
    QToolButton,
)

from . import icons

# Recipe-button states. "applied" = step is on; "available" = can be turned on;
# "unavailable" = its input is missing (disabled; the reason is the tooltip).
RECIPE_STATES = ("applied", "available", "unavailable")


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


def _recipe_action(
    toolbar: QToolBar, text: str, icon: str, color: str, state: str, reason: str
) -> QAction:
    """A three-state recipe toggle (mask / assign parts / correction)."""
    act = QAction(text, toolbar)
    act.setIcon(icons.ui(icon, color))
    act.setCheckable(True)
    if state == "applied":
        act.setChecked(True)
        act.setToolTip(f"{text}: applied — click to remove")
    elif state == "available":
        act.setChecked(False)
        act.setToolTip(f"{text}: available — click to apply")
    else:  # unavailable
        act.setEnabled(False)
        act.setToolTip(f"{text}: unavailable — {reason}")
    toolbar.addAction(act)
    return act


def _menu_button(toolbar: QToolBar, text: str, icon: str, color: str) -> QToolButton:
    """An icon button that drops a menu (instant popup)."""
    btn = QToolButton()
    btn.setText(text)
    btn.setToolTip(text)
    btn.setIcon(icons.ui(icon, color))
    btn.setAutoRaise(True)
    btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    menu = QMenu(btn)
    btn.setMenu(menu)
    toolbar.addWidget(btn)
    return btn


# -- Data toolset ------------------------------------------------------
def populate_data(
    toolbar: QToolBar,
    *,
    color: str,
    columns: list[str] | None = None,
    recipe_states: dict | None = None,
    sidebar_open: bool = False,
    on_toggle_sidebar=None,
    on_new_plot=None,
) -> None:
    columns = columns or []
    recipe_states = recipe_states or {}

    # Panel toggle — show/hide the side panel.
    panel = _action(toolbar, "Show/hide panel", "sidebar", color, checkable=True)
    panel.setChecked(sidebar_open)
    if on_toggle_sidebar is not None:
        panel.toggled.connect(on_toggle_sidebar)

    # Layer — which layer file is shown in the grid.
    toolbar.addWidget(_muted("Layer"))
    layer = QSpinBox()
    layer.setRange(1, 100_000)
    layer.setValue(1)
    layer.setFixedWidth(70)
    toolbar.addWidget(layer)
    toolbar.addSeparator()

    # Columns
    cols_btn = _menu_button(toolbar, "Show/hide columns", "show_hide", color)
    for name in columns:
        a = cols_btn.menu().addAction(name)
        a.setCheckable(True)
        a.setChecked(True)  # all visible by default (inert)
    _action(toolbar, "Rename column", "rename_column", color)
    _action(toolbar, "Add column", "add_column", color)
    _action(toolbar, "Remove column", "remove_column", color)
    toolbar.addSeparator()

    # Filters (query-time; on top of the cache).
    _action(toolbar, "Filter", "filter", color)
    _action(toolbar, "Remove filter", "remove_filter", color)
    _action(toolbar, "Reset filters", "reset_filter", color)
    toolbar.addSeparator()

    # Load recipe (applied on top of the query). Three-state each.
    for key, label, reason in (
        ("mask", "Mask", "no STL found to mask with"),
        ("assign_parts", "Assign parts", "no parts CSV / DHXML found"),
        ("correction", "Correction", "no correction reference found"),
    ):
        state, why = recipe_states.get(key, ("unavailable", reason))
        _recipe_action(toolbar, label, key, color, state, why)
    toolbar.addSeparator()

    # New plot — dropdown of plot types (icon per type).
    plot_btn = _menu_button(toolbar, "New plot", "new_plot", color)
    for view_name in icons.PLOT_TYPE:
        a = plot_btn.menu().addAction(icons.for_view(view_name, color), view_name)
        if on_new_plot is not None:
            a.triggered.connect(lambda _c=False, n=view_name: on_new_plot(n))
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
