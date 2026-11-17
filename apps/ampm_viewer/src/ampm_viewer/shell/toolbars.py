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

from PyQt6.QtGui import QAction, QActionGroup
from PyQt6.QtWidgets import (
    QLabel,
    QMenu,
    QSizePolicy,
    QSpinBox,
    QToolBar,
    QToolButton,
    QWidget,
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


def _muted(text: str) -> QLabel:
    lab = QLabel(text)
    return lab


class _StayOpenMenu(QMenu):
    """A menu that stays open when toggling checkable items (multi-select).

    Only intercepts releases once the mouse has moved onto an item. The release
    from the opening click (InstantPopup opens on press) passes through to the
    base class untouched, so the menu opens normally instead of closing at once.
    """

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._armed = False  # don't intercept the opening click's release
        super().showEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self._armed = True
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if getattr(self, "_armed", False):
            action = self.actionAt(event.pos())
            if action is not None and action.isCheckable() and action.isEnabled():
                action.setChecked(not action.isChecked())  # toggled; keep open
                return
        super().mouseReleaseEvent(event)


def _menu_button(
    toolbar: QToolBar, text: str, icon: str, color: str, *, stay_open: bool = False
) -> QToolButton:
    """An icon button that drops a menu (instant popup)."""
    btn = QToolButton()
    btn.setText(text)
    btn.setToolTip(text)
    btn.setIcon(icons.ui(icon, color))
    btn.setAutoRaise(True)
    btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    menu = _StayOpenMenu(btn) if stay_open else QMenu(btn)
    btn.setMenu(menu)
    toolbar.addWidget(btn)
    return btn


_RECORDING_RED = "#d93025"  # the Stop button while a macro is recording

# -- Data toolset ------------------------------------------------------
def populate_data(
    toolbar: QToolBar,
    *,
    color: str,
    columns: list[str] | None = None,
    hidden_columns: set | None = None,
    removed_columns: list[str] | None = None,
    layers: list[int] | None = None,
    current_layer: int | None = None,
    sidebar_open: bool = False,
    on_toggle_sidebar=None,
    on_layer_changed=None,
    on_column_visibility=None,
    on_rename=None,
    on_add_derive=None,
    on_add_label=None,
    on_add_excel=None,
    on_remove_column=None,
    on_restore_column=None,
    on_reset_selection=None,
    has_parts=False,
    part_has_csv=False,
    on_part_calc=None,
    on_part_import=None,
    on_filter=None,
    on_remove_filter=None,
    on_reset_filter=None,
    on_new_plot=None,
    on_plot_library=None,
    on_export_excel=None,
    recording: bool = False,
    on_macro_record=None,
    on_macro_run=None,
    recent_macros: list[tuple[str, str]] | None = None,
    folder_macros: list[tuple[str, str]] | None = None,
    on_open_macro_folder=None,
) -> None:
    columns = columns or []

    # Panel toggle — show/hide the side panel.
    panel = _action(toolbar, "Show/hide panel", "sidebar", color, checkable=True)
    panel.setChecked(sidebar_open)
    if on_toggle_sidebar is not None:
        panel.toggled.connect(on_toggle_sidebar)

    # Layer — which layer the grid shows (grid-only; plots carry their own span).
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

    # Columns — show/hide reflects the grid's current hidden set.
    cols_btn = _menu_button(
        toolbar, "Show/hide columns", "show_hide", color, stay_open=True
    )
    hidden = hidden_columns or set()
    for name in columns:
        a = cols_btn.menu().addAction(name)
        a.setCheckable(True)
        a.setChecked(name not in hidden)
        if on_column_visibility is not None:
            a.toggled.connect(lambda vis, n=name: on_column_visibility(n, vis))
    rename = _action(toolbar, "Rename column", "rename_column", color)
    if on_rename is not None:
        rename.triggered.connect(lambda: on_rename())
    # Add column — a menu of sources. "Derive column" is a row-wise formula over
    # existing columns; "Add from Excel" joins external key/value data.
    add_btn = _menu_button(toolbar, "Add column", "add_column", color)
    a_derive = add_btn.menu().addAction("Calculation")
    if on_add_derive is not None:
        a_derive.triggered.connect(lambda: on_add_derive())
    a_label = add_btn.menu().addAction("Label")
    if on_add_label is not None:
        a_label.triggered.connect(lambda: on_add_label())
    a_excel = add_btn.menu().addAction("Excel")
    if on_add_excel is not None:
        a_excel.triggered.connect(lambda: on_add_excel())
    else:
        a_excel.setEnabled(False)
    # Restore a previously removed source column (only shown when there are any).
    removed = removed_columns or []
    if removed:
        restore = add_btn.menu().addMenu("Restore column")
        for name in removed:
            act = restore.addAction(name)
            if on_restore_column is not None:
                act.triggered.connect(lambda _c=False, n=name: on_restore_column(n))
    # Remove acts on the grid's selected column(s); removal differs from hiding
    # (the column leaves the data, not just the view).
    remove = _action(toolbar, "Remove column", "remove_column", color)
    if on_remove_column is not None:
        remove.triggered.connect(lambda: on_remove_column())
    reset_sel = _action(toolbar, "Reset selection", "clear_sel", color)
    if on_reset_selection is not None:
        reset_sel.triggered.connect(lambda: on_reset_selection())
    toolbar.addSeparator()

    # Parts — contextual: only shown once a successful part assignment gives a
    # usable part_id, so these part-wise actions can count on it.
    if has_parts:
        parts_btn = _menu_button(toolbar, "Parts", "assign_parts", color)
        pcalc = parts_btn.menu().addAction("Per-part calculation…")
        if on_part_calc is not None:
            pcalc.triggered.connect(lambda: on_part_calc())
        pimport = parts_btn.menu().addAction("Import from parts CSV…")
        if on_part_import is not None and part_has_csv:
            pimport.triggered.connect(lambda: on_part_import())
        else:
            pimport.setEnabled(False)  # contextual: needs a parts CSV
            pimport.setToolTip("No QuantAM parts CSV configured for this build.")
        toolbar.addSeparator()

    # Filters (query-time; on top of the cache). Mask / assign-parts /
    # correction are not here — they're defined with the DataStore in the
    # backstage setup page.
    flt = _action(toolbar, "Filter", "filter", color)
    if on_filter is not None:
        flt.triggered.connect(lambda: on_filter())
    rmf = _action(toolbar, "Remove filter", "remove_filter", color)
    if on_remove_filter is not None:
        rmf.triggered.connect(lambda: on_remove_filter())
    rsf = _action(toolbar, "Reset filters", "reset_filter", color)
    if on_reset_filter is not None:
        rsf.triggered.connect(lambda: on_reset_filter())
    toolbar.addSeparator()

    # New plot — dropdown of plot types (icon per type).
    plot_btn = _menu_button(toolbar, "New plot", "new_plot", color)
    for view_name in icons.PLOT_TYPE:
        a = plot_btn.menu().addAction(icons.for_view(view_name, color), view_name)
        if on_new_plot is not None:
            a.triggered.connect(lambda _c=False, n=view_name: on_new_plot(n))
    if on_plot_library is not None:
        plot_btn.menu().addSeparator()
        lib = plot_btn.menu().addAction(
            icons.ui("plot_library", color), "Open from the plot library…")
        lib.triggered.connect(lambda _c=False: on_plot_library())
    toolbar.addSeparator()

    # Export
    xls = _action(toolbar, "Export to Excel", "export_excel", color)
    if on_export_excel is not None:
        xls.triggered.connect(lambda: on_export_excel())
    else:
        xls.setEnabled(False)
    toolbar.addSeparator()

    # Macros — record the actions performed here, save them to a file, and run
    # a saved macro. The record button turns into a (red) Stop while recording;
    # a macro can't be run in the middle of recording one.
    if recording:
        rec = _action(toolbar, "Stop recording and save the macro", "macro_stop",
                      _RECORDING_RED)
    else:
        rec = _action(toolbar, "Record a macro", "macro_record", color)
    if on_macro_record is not None:
        rec.triggered.connect(lambda: on_macro_record())
    recent_macros = list(recent_macros or [])
    seen = {p for _, p in recent_macros}
    folder_macros = [(n, p) for n, p in (folder_macros or []) if p not in seen]
    if (recent_macros or folder_macros) and on_macro_run is not None \
            and not recording:
        # Recent macros, then the rest of the macro folder, one click away;
        # Browse… for any other file.
        run_btn = _menu_button(toolbar, "Run a macro", "macro_run", color)
        menu = run_btn.menu()
        menu.setToolTipsVisible(True)
        for title, items in (("Recent", recent_macros),
                             ("Macro folder", folder_macros)):
            if not items:
                continue
            menu.addSection(title)
            for label, path in items:
                act = menu.addAction(label)
                act.setToolTip(path)
                act.triggered.connect(lambda _=False, p=path: on_macro_run(p))
        menu.addSeparator()
        menu.addAction("Browse…").triggered.connect(lambda: on_macro_run())
        if on_open_macro_folder is not None:
            menu.addAction("Open macro folder").triggered.connect(
                lambda: on_open_macro_folder())
    else:
        run = _action(toolbar, "Run a macro from a file", "macro_run", color)
        if on_macro_run is not None and not recording:
            run.triggered.connect(lambda: on_macro_run())
        else:
            run.setEnabled(False)


# -- Plot toolset ------------------------------------------------------
def populate_plot(
    toolbar: QToolBar, *, color: str, controls=(), value=None, on_control=None,
    sidebar_open: bool = False, on_toggle_sidebar=None, on_popout=None,
    on_dock=None,
) -> None:
    """The plot toolset, built from the plot's own controls.

    ``controls`` is what the plot offers right now (``PlotTab.controls()``, a
    list of ``plotcontrols.Control``), already in toolbar order; nothing here
    knows which plot kinds have which buttons. ``value(key)`` gives a
    control's current value, and ``on_control(key, value)`` applies one
    (``value`` is None for one-shot controls).
    """
    value = value or (lambda _key: None)

    def fire(key, v=None):
        if on_control is not None:
            on_control(key, v)

    # Panel toggle: same control as the Data toolbar.
    panel = _action(toolbar, "Show/hide panel", "sidebar", color, checkable=True)
    panel.setChecked(sidebar_open)
    if on_toggle_sidebar is not None:
        panel.toggled.connect(on_toggle_sidebar)

    group = None
    for c in controls:
        if c.group != group:  # a separator between groups
            toolbar.addSeparator()
            group = c.group
        if c.kind == "toggle":
            act = _action(toolbar, c.label, c.icon, color, checkable=True)
            act.setChecked(bool(value(c.key)))
            act.toggled.connect(lambda on, k=c.key: fire(k, on))
        elif c.kind == "action":
            act = _action(toolbar, c.label, c.icon, color)
            act.triggered.connect(lambda _=False, k=c.key: fire(k))
        elif c.kind in ("choice", "menu"):
            btn = _menu_button(toolbar, c.label, c.icon, color)
            menu = btn.menu()
            menu.setTitle(c.label)
            ticks = QActionGroup(menu) if c.kind == "choice" else None
            current = value(c.key)
            for v, text in c.choices:
                act = menu.addAction(text)
                if ticks is not None:  # exclusive: the current value ticked
                    act.setCheckable(True)
                    act.setChecked(v == current)
                    ticks.addAction(act)
                act.triggered.connect(lambda _=False, k=c.key, v=v: fire(k, v))

    # Pop out / dock in: pushed to the far right with an expanding spacer.
    spacer = QWidget()
    spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    toolbar.addWidget(spacer)
    if on_popout is not None:
        pop = _action(toolbar, "Pop out", "popout", color)
        pop.triggered.connect(lambda: on_popout())
    if on_dock is not None:
        dock = _action(toolbar, "Dock in", "dockin", color)
        dock.triggered.connect(lambda: on_dock())
