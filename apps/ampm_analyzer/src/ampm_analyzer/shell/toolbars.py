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

import bisect

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


class LayerSpinBox(QSpinBox):
    """A spinbox constrained to the layers that actually exist.

    Stepping moves to the next/previous available layer; a typed value snaps to
    the nearest available one on commit. So the control can never land on a
    missing layer.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._layers: list[int] = []
        self.editingFinished.connect(self._snap)

    def set_layers(self, layers: list[int], current: int | None = None) -> None:
        self._layers = sorted(layers)
        if not self._layers:
            self.setRange(0, 0)
            return
        self.setRange(self._layers[0], self._layers[-1])
        if current is None or current not in self._layers:
            current = self._layers[0]
        self.setValue(current)

    def _index_of(self, value: int) -> int:
        if not self._layers:
            return 0
        i = bisect.bisect_left(self._layers, value)
        if i < len(self._layers) and self._layers[i] == value:
            return i
        return min(
            range(len(self._layers)), key=lambda k: abs(self._layers[k] - value)
        )

    def stepBy(self, steps: int) -> None:
        if not self._layers:
            return
        i = self._index_of(self.value())
        j = max(0, min(len(self._layers) - 1, i + steps))
        self.setValue(self._layers[j])

    def _snap(self) -> None:
        if not self._layers:
            return
        nearest = self._layers[self._index_of(self.value())]
        if nearest != self.value():
            self.setValue(nearest)


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
    layers: list[int] | None = None,
    current_layer: int | None = None,
    sidebar_open: bool = False,
    on_toggle_sidebar=None,
    on_layer_changed=None,
    on_new_plot=None,
) -> None:
    columns = columns or []

    # Panel toggle — show/hide the side panel.
    panel = _action(toolbar, "Show/hide panel", "sidebar", color, checkable=True)
    panel.setChecked(sidebar_open)
    if on_toggle_sidebar is not None:
        panel.toggled.connect(on_toggle_sidebar)

    # Layer — which layer file is shown in the grid (constrained to real layers).
    toolbar.addWidget(_muted("Layer"))
    layer = LayerSpinBox()
    layer.setFixedWidth(80)
    if layers:
        layer.set_layers(layers, current_layer)
    else:
        layer.setEnabled(False)
    if on_layer_changed is not None:
        layer.valueChanged.connect(on_layer_changed)
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

    # Filters (query-time; on top of the cache). Mask / assign-parts /
    # correction are not here — they're defined with the DataStore in the
    # backstage setup page.
    _action(toolbar, "Filter", "filter", color)
    _action(toolbar, "Remove filter", "remove_filter", color)
    _action(toolbar, "Reset filters", "reset_filter", color)
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
