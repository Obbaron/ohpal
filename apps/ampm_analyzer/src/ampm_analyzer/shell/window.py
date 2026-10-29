"""The main window: tab strip, context-swapping toolbar, dock, status bar.

Layout order, top to bottom: the tab strip, then the context toolbar, then the
tab's content. To put the toolbar *below* the tabs (a QMainWindow toolbar area
always sits above the central widget), the tab bar is decoupled from the
content: a QTabBar drives a QStackedWidget, with the toolbar between them in the
central layout.

Only *structural* navigation is wired — opening the Data tab, spawning Plot
tabs, swapping the toolbar/dock per active tab, and the status helpers. All the
actual data and plot actions are inert, to be connected in a later pass.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTabBar,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import icons, theme, toolbars, uistate
from .backstage import Backstage
from .controller import AppController
from .data_tab import DataTab
from .dock import SidePanel
from .plot_tab import PlotTab
from .state import BuildSession

APP_TITLE = "AMPM Analyzer"


class MainWindow(QMainWindow):
    def __init__(self, log_bus=None) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1300, 820)

        from .logconsole import LogBus

        self.log_bus = log_bus if log_bus is not None else LogBus()

        # Central area, stacked vertically: tab strip, then toolbar, then the
        # active tab's content.
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setCentralWidget(central)

        # Tab strip (view switcher) with the "+" new-plot button alongside it.
        self.tabbar = QTabBar()
        self.tabbar.setExpanding(False)
        self.tabbar.setDrawBase(False)
        self.tabbar.setDocumentMode(True)
        self.tabbar.setTabsClosable(True)
        self.tabbar.setMovable(False)

        # No "+" new-plot shortcut: creating a plot needs setup, so plots are
        # created from the Data toolbar's "New plot" button instead.
        tab_row = QWidget()
        tab_row.setObjectName("TabRow")
        row = QHBoxLayout(tab_row)
        row.setContentsMargins(4, 2, 4, 0)
        row.setSpacing(2)
        row.addWidget(self.tabbar)
        row.addStretch(1)
        # Global cluster, pinned right of the tabs — persistent on every tab,
        # including File (where the context toolbar is hidden).
        color = self._icon_color()
        self._global_btns: dict[str, QToolButton] = {}
        for tip, key in (("Undo", "undo"), ("Redo", "redo"), ("Help", "help"), ("Settings", "settings")):
            btn = QToolButton()
            btn.setToolTip(tip)
            btn.setAutoRaise(True)
            btn.setIconSize(QSize(18, 18))
            btn.setIcon(icons.ui(key, color))
            if key == "settings":
                btn.clicked.connect(self._open_settings)
            row.addWidget(btn)
            self._global_btns[key] = btn
        root.addWidget(tab_row)

        # Context-swapping toolbar — now a plain widget in the layout, below the
        # tab strip. Contents rebuilt per active tab. Icon-only (Office-style);
        # each action's text becomes its tooltip.
        self.toolbar = QToolBar("Main")
        self.toolbar.setMovable(False)
        self.toolbar.setFloatable(False)
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.toolbar.setIconSize(QSize(18, 18))
        root.addWidget(self.toolbar)

        # Content row: the tab pages, with the side panel beside them (so the
        # panel sits under the tabs/toolbar, not up at the title bar). A
        # splitter lets the user resize it.
        self.stack = QStackedWidget()
        self.panel = SidePanel()
        self.panel.closed.connect(self._close_panel)
        self._wire_panel_controls()
        self.panel.setVisible(False)  # hidden by default; opens when relevant

        content = QSplitter(Qt.Orientation.Horizontal)
        content.addWidget(self.panel)  # panel on the left
        content.addWidget(self.stack)
        content.setStretchFactor(0, 0)
        content.setStretchFactor(1, 1)
        content.setCollapsible(0, True)
        content.setCollapsible(1, False)
        content.setSizes([260, 1040])
        root.addWidget(content, 1)

        self._init_statusbar()

        # Session + controller: the controller owns ohpal + threading; the
        # window only reacts to session signals (on the main thread).
        self.session = BuildSession()
        self.controller = AppController(self, self.session)
        self.session.loadStarted.connect(self._on_load_started)
        self.session.buildLoaded.connect(self._on_build_loaded)
        self.session.setupRequired.connect(self._on_setup_required)
        self.session.cacheProgress.connect(self._on_cache_progress)
        self.session.queryReady.connect(self._on_query_ready)
        self.session.loadFailed.connect(self._on_load_failed)

        # File (backstage) tab — pinned left-most, non-closable.
        self.backstage = Backstage()
        self.backstage.newRequested.connect(self.controller.new_build)
        self.backstage.openRequested.connect(self.controller.open_build)
        self.backstage.openRecentRequested.connect(self.controller.open_recent)
        self.backstage.createExcelRequested.connect(
            lambda: self.set_status("Create Excel from AMPM — not wired yet")
        )
        self.backstage.datastoreBuildRequested.connect(self._on_build_requested)
        self.backstage.apply_icons(color)
        self._add_page(self.backstage, "File", closable=False)

        self._data_tab: DataTab | None = None
        self._plot_tabs: list = []  # open plot tabs, re-fed the shared result
        self._active_plot = None  # the plot tab the toolbar/panel controls drive
        self._pending_grid_state: bytes | None = None  # per-build column layout
        self._grid_cache_dir = None  # where to persist the layout
        self._last_columns: list[str] | None = None  # to rebuild toolbar on change

        # Theme: "auto" follows the OS (and keeps following live), or a fixed
        # "light" / "dark". The launch scheme was applied in app.py.
        self._theme_choice = "auto"
        from PyQt6.QtWidgets import QApplication

        hints = QApplication.instance().styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(self._on_os_scheme_changed)

        self.tabbar.currentChanged.connect(self._on_tab_changed)
        self.tabbar.tabCloseRequested.connect(self._close_tab)

        self.tabbar.setCurrentIndex(0)
        self._on_tab_changed(0)
        self.set_status("Ready")

    # -- page/tab management (tab bar + stack kept in lockstep) --------
    def _add_page(self, widget: QWidget, title: str, *, closable: bool = True) -> int:
        index = self.tabbar.addTab(title)
        self.stack.insertWidget(index, widget)
        if not closable:
            self._lock_tab(index)
        return index

    def _insert_page(
        self, index: int, widget: QWidget, title: str, *, closable: bool = True
    ) -> int:
        self.tabbar.insertTab(index, title)
        self.stack.insertWidget(index, widget)
        if not closable:
            self._lock_tab(index)
        return index

    def _lock_tab(self, index: int) -> None:
        """Remove the close button so this tab can't be closed."""
        for pos in (
            QTabBar.ButtonPosition.RightSide,
            QTabBar.ButtonPosition.LeftSide,
        ):
            btn = self.tabbar.tabButton(index, pos)
            if btn is not None:
                btn.deleteLater()
            self.tabbar.setTabButton(index, pos, None)

    def _select_widget(self, widget: QWidget) -> None:
        index = self.stack.indexOf(widget)
        if index >= 0:
            self.tabbar.setCurrentIndex(index)

    def _ensure_data_tab(self) -> DataTab:
        """Create the single Data tab if needed; return it (no side prompts)."""
        if self._data_tab is None:
            self._data_tab = DataTab()
            self._data_tab.set_persisted_state(self._pending_grid_state)
            self._data_tab.layoutChanged.connect(self._save_ui)
            self._insert_page(1, self._data_tab, "Data", closable=False)
            self.backstage.set_build_loaded(True)  # reveal the DataStore entry
        return self._data_tab

    def _save_ui(self) -> None:
        """Persist grid layout + derivations + removed columns for this build."""
        if self._grid_cache_dir is None:
            return
        header = self._data_tab.current_state() if self._data_tab is not None else None
        uistate.save_state(
            self._grid_cache_dir,
            grid_header=header,
            derivations=self.session.derivations,
            removed=self.session.removed,
        )

    # -- load lifecycle (driven by BuildSession signals) ---------------
    def _on_load_started(self, label: str) -> None:
        self.backstage.set_loading(True)
        self.show_progress(True, busy=True)
        self.set_status(f"Loading {label}…")

    def _on_build_loaded(self, store) -> None:
        # Build identified — set the title + reveal the DataStore entry. The
        # Data tab is only opened once there's a query result (see _on_query_ready),
        # so New (which goes to setup first) doesn't flash an empty grid.
        self.setWindowTitle(f"{APP_TITLE} — {self.session.build_name}")
        self.backstage.set_build_loaded(True)
        self.backstage.refresh_recents()  # the just-loaded build is now recent
        # Restore this build's saved UI state. set_store has just cleared the
        # session's derivations/removed; put the saved ones back before the first
        # query, so the controller's pipeline applies them to the first result.
        self._grid_cache_dir = store.cache_dir
        state = uistate.load_state(store.cache_dir)
        self.session.derivations = list(state["derivations"])
        self.session.removed = list(state["removed"])
        self._pending_grid_state = state["grid_header"]
        if self._data_tab is not None:
            self._data_tab.set_persisted_state(self._pending_grid_state)

    def _on_setup_required(self, payload) -> None:
        config, layers, columns, exists = payload
        # (Re)building a DataStore via setup = a fresh start: drop any per-build
        # UI state loaded from this cache dir (derived/removed columns, grid
        # layout) and delete its file, so a stale layout isn't restored.
        self.session.derivations = []
        self.session.removed = []
        self._pending_grid_state = None
        if self._data_tab is not None:
            self._data_tab.set_persisted_state(None)
        if self._grid_cache_dir is not None:
            uistate.clear(self._grid_cache_dir)
        self.backstage.set_loading(False)
        self.show_progress(False)
        self.backstage.set_datastore_config(config, layers, columns)
        self.backstage.set_datastore_exists(exists)
        self.backstage.show_datastore_page()
        self.tabbar.setCurrentIndex(0)  # File tab
        self.set_status("Setting up DataStore…")

    def _on_build_requested(self) -> None:
        form = self.backstage.ds_form
        self.controller.build_datastore(
            form.scope(), form.thickness(), form.recipe()
        )

    def _on_cache_progress(self, done: int, total: int, layer: int) -> None:
        self._progress.setRange(0, total)
        self._progress.setValue(done)
        self._progress.setVisible(True)
        self.set_status(f"Building cache: layer {layer} ({done}/{total})")

    def _on_query_ready(self, result) -> None:
        self.backstage.set_loading(False)
        self.show_progress(False)
        self._ensure_data_tab()
        # Populate the model BEFORE selecting the tab: switching tabs rebuilds
        # the toolbar (incl. the Show/hide columns menu), which must see the
        # real columns, not an empty model.
        cols = list(result.df.columns)
        changed = cols != self._last_columns
        self._last_columns = cols
        was_on_data = self.stack.currentWidget() is self._data_tab
        self._data_tab.set_dataframe(result.df)
        self._data_tab.set_filters(
            self.controller.filters(), result.shown_rows, result.total_rows,
            lambda idx: self.controller.remove_filter(idx),
        )
        self._select_widget(self._data_tab)
        # If we were already on the Data tab the selection is a no-op, so a
        # changed column set (e.g. a new derived column) needs an explicit
        # toolbar rebuild to refresh the Show/hide list.
        if changed and was_on_data:
            self._sync_toolbar(self.tabbar.currentIndex())
        lo, hi = result.layers
        where = f"layer {lo}" if lo == hi else f"layers {lo}–{hi}"
        capped = (
            f" (showing first {result.shown_rows:,})"
            if result.shown_rows < result.total_rows
            else ""
        )
        self.set_status(f"Loaded {where}: {result.total_rows:,} rows{capped}")

    def _on_load_failed(self, message: str) -> None:
        self.backstage.set_loading(False)
        self.show_progress(False)
        first_line = message.strip().splitlines()[-1] if message.strip() else message
        self.set_status(f"Load failed: {first_line}")
        self.log_bus.log_line(message)  # full traceback to the log

    def _new_plot(self, kind: str | None = None) -> None:
        from .plotspec import SCATTER_KINDS

        if self.session.result is None:
            self.set_status("Load a build before plotting.")
            return
        if kind not in SCATTER_KINDS:
            self.set_status(f"{kind}: not wired yet.")
            return
        from .plot_dialog import NewPlotDialog

        store = self.session.store
        columns = list(self.session.result.df.columns)
        layers = list(store.layers) if store is not None else []
        dlg = NewPlotDialog(kind, columns, layers, self.session.current_layer, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        spec = dlg.spec()
        span = dlg.span()  # ("all", None, None) or ("range", lo, hi)
        self._ensure_data_tab()
        tab = PlotTab(spec, span=span)
        tab.row_filter = self.controller.filters()  # snapshot the active filter
        self._plot_tabs.append(tab)
        index = self._add_page(tab, tab.title, closable=True)
        self.tabbar.setCurrentIndex(index)
        # Query this plot's own span, then shape + feed it.
        tab.set_loading(f"Querying {tab.span_label}…")
        self.controller.query_for(*span, lambda raw, t=tab: self._feed_plot(t, raw))

    def _feed_plot(self, tab, raw_df) -> None:
        if tab not in self._plot_tabs:
            return  # closed before the query returned
        tab.raw = raw_df
        tab.set_dataframe(self.controller.shape_filtered(raw_df, tab.row_filter))
        if tab is self._active_plot:  # data just arrived — refresh Min/Max etc.
            self.panel.sync_plot(tab.panel_state())

    def _reshape_plots(self) -> None:
        """Re-shape open plots from their raw span after a column change.

        Column shaping propagates live; each plot keeps its own snapshotted
        row filter (captured at creation), so filtered plots stay filtered.
        """
        for tab in self._plot_tabs:
            if getattr(tab, "raw", None) is not None:
                tab.set_dataframe(
                    self.controller.shape_filtered(tab.raw, tab.row_filter)
                )

    def _close_tab(self, index: int) -> None:
        widget = self.stack.widget(index)
        if widget is not None and widget.property("tabkind") == "plot":
            self.tabbar.removeTab(index)
            self.stack.removeWidget(widget)
            if widget in self._plot_tabs:
                self._plot_tabs.remove(widget)
            if hasattr(widget, "release"):
                widget.release()
            widget.deleteLater()

    def _wire_panel_controls(self) -> None:
        """Route side-panel controls to whichever plot is active."""
        p = self.panel

        def to_plot(fn):
            return lambda v: self._active_plot and fn(self._active_plot, v)

        p.markerSizeChanged.connect(to_plot(lambda t, v: t.set_marker_size(v)))
        p.markerSymbolChanged.connect(to_plot(lambda t, v: t.set_marker_symbol(v)))
        p.opacityChanged.connect(to_plot(lambda t, v: t.set_opacity(v)))
        p.colormapChanged.connect(to_plot(lambda t, v: t.set_colormap(v)))
        p.scaleChanged.connect(to_plot(lambda t, v: t.set_scale(v)))
        p.colorMinChanged.connect(to_plot(lambda t, v: t.set_color_min(v)))
        p.colorMaxChanged.connect(to_plot(lambda t, v: t.set_color_max(v)))

    def _on_tab_changed(self, index: int) -> None:
        if 0 <= index < self.stack.count():
            self.stack.setCurrentIndex(index)
        widget = self.stack.widget(index)
        self._active_plot = widget if widget in self._plot_tabs else None
        if self._active_plot is not None:
            self.panel.sync_plot(self._active_plot.panel_state())
        self._sync_toolbar(index)

    # -- status bar ----------------------------------------------------
    def _init_statusbar(self) -> None:
        sb = QStatusBar()
        self.setStatusBar(sb)

        self._log = QLabel("Ready")
        self._log.setObjectName("StatusLog")
        sb.addWidget(self._log, 1)

        self._progress = QProgressBar()
        self._progress.setFixedWidth(170)
        self._progress.setVisible(False)
        sb.addWidget(self._progress)

        self._log_btn = QToolButton()
        self._log_btn.setText("Show log")
        self._log_btn.setAutoRaise(True)
        self._log_btn.clicked.connect(self._open_log)
        sb.addPermanentWidget(self._log_btn)
        self._log_window = None

    def set_status(self, text: str) -> None:
        self._log.setText(text)
        self.log_bus.log_line(text)

    def _open_log(self) -> None:
        from .logconsole import LogWindow

        if self._log_window is None:
            self._log_window = LogWindow(self.log_bus, self)
        self._log_window.show()
        self._log_window.raise_()
        self._log_window.activateWindow()

    def show_progress(self, on: bool, *, busy: bool = True) -> None:
        if on and busy:
            self._progress.setRange(0, 0)  # indeterminate
        elif on:
            self._progress.setRange(0, 100)
        self._progress.setVisible(on)

    def _close_panel(self) -> None:
        """User dismissed the panel; it reopens when they revisit a plot tab."""
        self.panel.setVisible(False)

    # -- settings / theme ----------------------------------------------
    def _open_settings(self) -> None:
        from PyQt6.QtGui import QActionGroup, QCursor
        from PyQt6.QtWidgets import QMenu

        menu = QMenu(self)
        menu.addSection("Theme")
        group = QActionGroup(self)
        group.setExclusive(True)
        for label, choice in (("Auto (system)", "auto"), ("Light", "light"), ("Dark", "dark")):
            act = menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(choice == self._theme_choice)
            group.addAction(act)
            act.triggered.connect(lambda _checked, c=choice: self._set_theme_choice(c))
        menu.exec(QCursor.pos())

    def _icon_color(self) -> str:
        return theme.icon_color(QApplication.instance())

    def _apply_scheme(self, scheme: str) -> None:
        app = QApplication.instance()
        theme.apply_theme(app, scheme)
        icons.clear_cache()  # drop icons tinted for the old palette
        self._refresh_icons()

    def _refresh_icons(self) -> None:
        color = self._icon_color()
        for key, btn in self._global_btns.items():
            btn.setIcon(icons.ui(key, color))
        self._sync_toolbar(self.tabbar.currentIndex())  # rebuild with new colour
        self.backstage.apply_icons(color)

    def _set_theme_choice(self, choice: str) -> None:
        self._theme_choice = choice
        app = QApplication.instance()
        scheme = theme.initial_scheme(app) if choice == "auto" else choice
        self._apply_scheme(scheme)

    def _on_os_scheme_changed(self, *_) -> None:
        """When following the OS, re-apply as it flips light/dark."""
        if self._theme_choice == "auto":
            self._apply_scheme(theme.initial_scheme(QApplication.instance()))

    # -- toolbar swap --------------------------------------------------
    def _sync_toolbar(self, index: int) -> None:
        widget: QWidget | None = self.stack.widget(index)
        kind = widget.property("tabkind") if widget is not None else "file"

        # Panel: Plot auto-opens it; Data leaves it user-controlled (via the
        # toolbar toggle); File hides it.
        if kind == "plot":
            self.panel.show_for(kind)
            self.panel.setVisible(True)
        elif kind == "file":
            self.panel.setVisible(False)
        else:  # data — keep whatever the user set; just sync the page
            if self.panel.isVisible():
                self.panel.show_for(kind)

        self.toolbar.clear()
        if kind == "file":
            self.toolbar.hide()
            return

        self.toolbar.show()
        color = self._icon_color()
        if kind == "data":
            store = self.session.store
            dt = self._data_tab
            toolbars.populate_data(
                self.toolbar,
                color=color,
                columns=dt._columns if dt else None,
                hidden_columns=dt.hidden_columns() if dt else None,
                removed_columns=list(self.session.removed),
                layers=list(store.layers) if store is not None else None,
                current_layer=self.session.current_layer,
                sidebar_open=self.panel.isVisible(),
                on_toggle_sidebar=self._toggle_sidebar,
                on_layer_changed=self._on_layer_changed,
                on_column_visibility=(
                    (lambda n, v: dt.set_column_visible(n, v)) if dt else None
                ),
                on_add_derive=self._add_derive_column,
                on_add_label=self._add_group_label,
                on_remove_column=self._remove_columns,
                on_restore_column=self._restore_column,
                on_filter=self._on_filter,
                on_remove_filter=self.controller.remove_last_filter,
                on_reset_filter=self.controller.reset_filters,
                on_new_plot=lambda name=None: self._new_plot(name),
            )
        else:
            p = self._active_plot
            toolbars.populate_plot(
                self.toolbar,
                color=color,
                sidebar_open=self.panel.isVisible(),
                on_toggle_sidebar=self._toggle_sidebar,
                states=p.toggle_states() if p is not None else None,
                on_reset_view=lambda: p and p.reset_view(),
                on_axes=lambda v: p and p.set_axes_visible(v),
                on_grid=lambda v: p and p.set_grid_visible(v),
                on_bbox=lambda v: p and p.set_bbox_visible(v),
                on_legend=lambda v: p and p.set_legend_visible(v),
            )

    def _on_layer_changed(self, layer: int) -> None:
        self.controller.show_layer(layer)

    def _on_filter(self) -> None:
        dt = self._data_tab
        if dt is None:
            return
        from .filter_dialog import FilterConditionDialog

        dlg = FilterConditionDialog(dt._columns, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self.controller.add_filter(dlg.condition())

    def _add_derive_column(self) -> None:
        dt = self._data_tab
        if dt is None:
            return
        from .derive_dialog import DeriveColumnDialog

        taken = [d["name"] for d in self.session.derivations]
        dlg = DeriveColumnDialog(dt._columns, self, taken=taken)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, expr, group = dlg.result_values()
        err = self.controller.add_derivation(name, expr, group)
        if err:
            self.set_status(f"Derive column failed: {err}")
        else:
            by = f" by {group}" if group else ""
            self.set_status(f"Added derived column '{name}'{by}.")
            self._save_ui()
            self._reshape_plots()

    def _add_group_label(self) -> None:
        dt = self._data_tab
        if dt is None:
            return
        from .label_dialog import GroupLabelDialog

        taken = [d["name"] for d in self.session.derivations]
        dlg = GroupLabelDialog(dt._columns, self, taken=taken)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, rules, default = dlg.result_values()
        err = self.controller.add_label_derivation(name, rules, default)
        if err:
            self.set_status(f"Group label failed: {err}")
        else:
            self.set_status(f"Added label column '{name}' ({len(rules)} rule(s)).")
            self._save_ui()
            self._reshape_plots()

    def _remove_columns(self) -> None:
        dt = self._data_tab
        if dt is None:
            return
        names = dt.selected_columns()
        if not names:
            self.set_status("Select a column (click its header) to remove.")
            return
        blocked = self.controller.remove_columns(names)
        done = [n for n in names if n not in blocked]
        if done:
            self.set_status(f"Removed {len(done)} column(s): {', '.join(done)}.")
            self._save_ui()
            self._reshape_plots()
        if blocked:
            self.set_status(f"Can't remove required column(s): {', '.join(blocked)}.")

    def _restore_column(self, name: str) -> None:
        self.controller.restore_column(name)
        self.set_status(f"Restored column '{name}'.")
        self._save_ui()
        self._reshape_plots()

    def _toggle_sidebar(self, checked: bool) -> None:
        if checked:
            kind = self.stack.currentWidget().property("tabkind")
            self.panel.show_for(kind)
            self.panel.setVisible(True)
        else:
            self.panel.setVisible(False)

    # -- shutdown ------------------------------------------------------
    def closeEvent(self, event) -> None:
        self.controller.shutdown()  # stop any running worker thread
        super().closeEvent(event)
