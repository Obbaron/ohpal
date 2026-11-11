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
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTabBar,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import icons, macros, theme, toolbars, uistate
from .actions import Actions
from .backstage import Backstage
from .controller import AppController
from .data_tab import DataTab
from .dock import SidePanel
from .plot_tab import PlotTab
from .state import BuildSession

APP_TITLE = "AMPM Analyzer"


class _ElidingLabel(QLabel):
    """A status label that never drives the window width.

    A plain QLabel reports its full (non-wrapped) text width as its size hint,
    so a long status line (e.g. "Added 24 columns: …" listing every name) forces
    the status bar — and thus the window's minimum width — past the screen. A
    maximized window on Wayland can't grow to satisfy that, so Qt commits a
    buffer wider than the configured maximized surface and the compositor kills
    the connection with a protocol error. This label ignores its text width for
    layout and elides the shown text to whatever width it's given, keeping the
    full text as a tooltip.
    """

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__("", parent)
        self._full = text
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        self._apply()

    def setText(self, text: str) -> None:  # noqa: N802 — Qt override
        self._full = text or ""
        self.setToolTip(self._full)
        self._apply()

    def resizeEvent(self, event) -> None:  # noqa: N802 — Qt override
        super().resizeEvent(event)
        self._apply()

    def _apply(self) -> None:
        fm = self.fontMetrics()
        avail = max(0, self.width() - 4)
        super().setText(fm.elidedText(self._full, Qt.TextElideMode.ElideRight, avail))


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
        self.panel.columnRenamed.connect(self._rename_column_from_panel)
        self.panel.sigFigsChanged.connect(self._set_column_sigfigs)
        self._wire_panel_controls()
        self.panel.setVisible(False)  # hidden by default; opens when relevant
        # The Data tab keeps its own panel-open preference, so a plot tab
        # auto-opening the panel doesn't force it open on Data too.
        self._panel_data_open = False

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

        # Action layer: every shape/view-changing user action goes through it, so
        # each one is an undo step (and, later, a recordable macro step).
        self._quiet_refresh = False  # True while undo/redo re-shapes the grid
        self.actions = Actions(self, self.controller, self.session, parent=self)
        self.actions.history.changed.connect(self._sync_history_buttons)
        self._global_btns["undo"].clicked.connect(self._undo)
        self._global_btns["redo"].clicked.connect(self._redo)
        for keys, slot in (("Ctrl+Z", self._undo), ("Ctrl+Shift+Z", self._redo),
                           ("Ctrl+Y", self._redo)):
            QShortcut(QKeySequence(keys), self, activated=slot)
        self._sync_history_buttons()

        # Macro recorder: captures the actions committed between Record and Stop.
        self.recorder = macros.Recorder(self.actions, parent=self)
        self.recorder.changed.connect(self._on_recorder_changed)
        self._rec_was_active = False
        self._macro_dir: str | None = None  # last folder used for macro files

        # File (backstage) tab — pinned left-most, non-closable.
        self.backstage = Backstage()
        self.backstage.newRequested.connect(self.controller.new_build)
        self.backstage.openRequested.connect(self.controller.open_build)
        self.backstage.openRecentRequested.connect(self.controller.open_recent)
        self.backstage.createExcelRequested.connect(self.controller.create_excel)
        self.backstage.datastoreBuildRequested.connect(self._on_build_requested)
        self.backstage.apply_icons(color)
        self._add_page(self.backstage, "File", closable=False)

        self._data_tab: DataTab | None = None
        self._plot_tabs: list = []  # open plot tabs, re-fed the shared result
        self._detached: list = []  # popped-out plot windows (kept from GC)
        self._active_plot = None  # the plot tab the toolbar/panel controls drive
        self._pending_grid_state: bytes | None = None  # per-build column layout
        self._pending_grid_layout = ([], [], [])  # (columns, order, hidden) by name
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
            self._data_tab.set_persisted_state(
                self._pending_grid_state, *self._pending_grid_layout)
            self._data_tab.layoutChanged.connect(self._save_ui)
            self._data_tab.renameRequested.connect(self._rename_column)
            self._data_tab.columnActivated.connect(self._open_column_panel)
            self._data_tab.columnSelectionChanged.connect(self._on_column_selection)
            self._data_tab.set_renames(self.session.renames)  # for default layout
            self._insert_page(1, self._data_tab, "Data", closable=False)
            self.backstage.set_build_loaded(True)  # reveal the DataStore entry
        return self._data_tab

    def _save_ui(self) -> None:
        """Persist grid layout + derivations + removed columns for this build."""
        if self._grid_cache_dir is None:
            return
        dt = self._data_tab
        header = dt.current_state() if dt is not None else None
        cols, order, hidden = dt.layout_names() if dt is not None else ([], [], [])
        uistate.save_state(
            self._grid_cache_dir,
            grid_header=header,
            derivations=self.session.derivations,
            removed=self.session.removed,
            filters=self.controller.filters(),
            grid_columns=cols,
            grid_order=order,
            grid_hidden=hidden,
            part_method=(self.controller.current_config() or {}).get("METHOD") or "",
            apply_mask=self.controller.apply_mask(),
            correction=self.controller.correction(),
            load_columns=self.controller.load_columns(),
            renames=self.session.renames,
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
        # Restore this build's saved UI state first. set_store has just cleared
        # the session's derivations/removed/renames; put the saved ones back
        # before the first query, so the controller's pipeline applies them to
        # the first result (and the setup form below can reflect the renames).
        self._grid_cache_dir = store.cache_dir
        self._reset_history()  # undo history (and a recording) is per build
        state = uistate.load_state(store.cache_dir)
        self.session.derivations = list(state["derivations"])
        self.session.removed = list(state["removed"])
        self.session.renames = dict(state["renames"])  # restore column renames
        self.controller.set_filters(state["filters"])  # restore persisted filters
        # Populate the DataStore setup form now, so it's ready if the user
        # navigates back to it to rebuild — even when the build opened straight
        # from cache (which skips the setup page on load). Pass the restored
        # renames so a rebuild preserves them instead of reapplying the default.
        self.backstage.set_datastore_config(
            self.controller.current_config(), list(store.layers),
            list(store.columns), dict(self.session.renames),
            self.controller.load_columns() or None,
        )
        self.backstage.set_datastore_exists(self.controller.cache_exists(store))
        self._pending_grid_state = state["grid_header"]
        self._pending_grid_layout = (
            state["grid_columns"], state["grid_order"], state["grid_hidden"])
        if self._data_tab is not None:
            self._data_tab.set_persisted_state(
                self._pending_grid_state, *self._pending_grid_layout)

    def _reset_build_state(self) -> None:
        """Drop everything remembered for this build's DataStore — derived and
        removed columns, filters, the grid's column layout and display settings,
        the undo history and the saved state file — so a (re)build starts
        clean. The build recipe (mask, parts, correction, renames) is written
        afresh by the build itself."""
        self._reset_history()
        # Plots drawn from the old DataStore are stale now; close them. (Popped-
        # out plot windows are self-contained copies and are left alone.)
        for tab in list(self._plot_tabs):
            self._close_plot(tab)
        self.session.derivations = []
        self.session.removed = []
        self.controller.set_filters([])
        self._pending_grid_state = None
        self._pending_grid_layout = ([], [], [])
        if self._data_tab is not None:
            self._data_tab.set_persisted_state(None)
            self._data_tab.clear_column_settings()
        if self._grid_cache_dir is not None:
            uistate.clear(self._grid_cache_dir)

    def _on_setup_required(self, payload) -> None:
        config, layers, columns, exists = payload
        # (Re)building a DataStore via setup = a fresh start: drop any per-build
        # UI state loaded from this cache dir (derived/removed columns, grid
        # layout) and delete its file, so a stale layout isn't restored.
        self._reset_build_state()
        self.backstage.set_loading(False)
        self.show_progress(False)
        self.backstage.set_datastore_config(config, layers, columns)
        self.backstage.set_datastore_exists(exists)
        self.backstage.show_datastore_page()
        self.tabbar.setCurrentIndex(0)  # File tab
        self.set_status("Setting up DataStore…")

    def _on_build_requested(self) -> None:
        form = self.backstage.ds_form
        # A (re)build can change the loaded column set, so force the next query
        # to refresh the toolbar (Show/hide columns menu) rather than treating
        # the columns as unchanged.
        self._last_columns = None
        # A (re)build is a clean slate — also when rebuilding a DataStore that
        # is already open, which never passes through the setup-required reset.
        self._reset_build_state()
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
        self._data_tab.set_dataframe(result.df)
        self._data_tab.set_filters(
            self.controller.filters(), result.shown_rows, result.total_rows,
            self._remove_filter_at, self._edit_filter_at,
        )
        if not self._quiet_refresh:
            self._select_widget(self._data_tab)
        # A changed column set (new derived column, or a rebuild with a
        # different selection) needs the toolbar rebuilt so the Show/hide menu
        # matches the grid. When the tab actually switched, the switch already
        # rebuilt it with the fresh columns; this covers the no-switch case
        # (and a harmless second rebuild otherwise).
        if changed:
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
        from .plotspec import PLOT_KINDS

        if self.session.result is None:
            self.set_status("Load a build before plotting.")
            return
        if kind not in PLOT_KINDS:
            self.set_status(f"{kind}: not wired yet.")
            return
        from .plot_dialog import NewPlotDialog

        store = self.session.store
        columns = list(self.session.result.df.columns)
        layers = list(store.layers) if store is not None else []
        dlg = NewPlotDialog(kind, columns, layers, self.session.current_layer,
                            self, renames=self.session.renames)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        spec = dlg.spec()
        span = dlg.span()  # ("all", None, None) or ("range", lo, hi)
        self._open_plot(spec, span)
        # An output, not an undo step — but a macro being recorded keeps it.
        from dataclasses import asdict

        self.actions.note("plot", spec=asdict(spec), span=list(span))

    def _open_plot(self, spec, span):
        """Create a plot tab for ``spec`` over ``span`` and start its query.
        Shared by the New-plot dialog and by macro plot steps."""
        store = self.session.store
        layers = list(store.layers) if store is not None else []
        self._ensure_data_tab()
        tab = PlotTab(spec, span=span, layers=layers)
        tab.row_filter = self.controller.filters()  # snapshot the active filter
        self._plot_tabs.append(tab)
        if spec.is_layer_viewer:  # the scrub slider re-queries its layer
            tab.layerChanged.connect(lambda L, t=tab: self._scrub_layer(t, L))
        tab.titleChanged.connect(lambda name, t=tab: self._on_plot_renamed(t, name))
        index = self._add_page(tab, tab.title, closable=True)
        self.tabbar.setCurrentIndex(index)
        # Query this plot's own span, then shape + feed it.
        tab.set_loading(f"Querying {tab.span_label}…")
        self.controller.query_for(*span, lambda raw, t=tab: self._feed_plot(t, raw))
        return tab

    def _close_plot(self, tab) -> None:
        """Close a plot tab (a macro that failed takes back the plots it opened)."""
        idx = self.stack.indexOf(tab)
        if idx >= 0:
            self._close_tab(idx)

    def _on_plot_renamed(self, tab, name: str) -> None:
        """A plot's on-canvas title was renamed; mirror it onto its tab."""
        idx = self.stack.indexOf(tab)
        if idx >= 0:
            self.tabbar.setTabText(idx, name)

    def _scrub_layer(self, tab, layer: int) -> None:
        """Re-query a Layer Viewer's chosen layer and feed it (camera stays
        put — only the first render frames the view)."""
        if tab not in self._plot_tabs:
            return
        tab.span = ("single", layer, layer)
        if tab.context is not None:
            # Self-contained: query the tab's own build directly (synchronous —
            # a single cached layer is cheap, and this is a rare docked-back
            # interaction) and shape it with the tab's frozen context.
            try:
                from .controller import _PLOT_SAMPLE_ROWS
                df = tab.context["store"].query(
                    layers=(layer, layer), columns=None,
                    sample_to=_PLOT_SAMPLE_ROWS)
            except Exception as exc:  # noqa: BLE001
                self.set_status(f"Couldn't re-query that layer: {exc}")
                return
            self._feed_plot(tab, df)
        else:
            self.controller.query_for(
                "single", layer, layer,
                lambda raw, t=tab: self._feed_plot(t, raw))

    def _popout_plot(self) -> None:
        """Detach the active plot into its own window — a self-contained copy
        that keeps its build, so it survives the main window switching builds."""
        p = self._active_plot
        if p is None:
            return
        if getattr(p, "raw", None) is None:
            self.set_status("Let the plot finish loading before popping it out.")
            return
        from .plot_window import DetachedPlotWindow

        store = self.session.store
        layers = list(p._layers) or (list(store.layers) if store else [])
        context = {
            "store": store,
            "build_name": self.session.build_name,
            "derivations": list(self.session.derivations),
            "removed": list(self.session.removed),
            "row_filter": list(p.row_filter),
            "renames": dict(self.session.renames),
        }
        win = DetachedPlotWindow(
            spec=p.spec, span=p.span, layers=layers, raw=p.raw,
            appearance=p.appearance(), context=context,
            icon_color=self._icon_color(),
        )
        win.closed.connect(self._on_detached_closed)
        win.dockRequested.connect(self._dock_plot)
        self._detached.append(win)
        win.show()
        # Remove the original docked tab (the window now owns this plot).
        idx = self.stack.indexOf(p)
        if idx >= 0:
            self._close_tab(idx)

    def _on_detached_closed(self, win) -> None:
        if win in self._detached:
            self._detached.remove(win)

    def _dock_plot(self, win) -> None:
        """Re-add a floating window's plot as a self-contained tab, then close
        the window. The tab keeps the window's frozen context, so a plot from
        another build docks in cleanly alongside the current one."""
        if self.session.result is None:
            self.set_status("Load a build before docking a plot in.")
            return
        payload = win.dock_payload()
        self._ensure_data_tab()
        spec = payload["spec"]
        tab = PlotTab(spec, span=payload["span"], layers=payload["layers"])
        tab.row_filter = payload["context"]["row_filter"]
        tab.context = payload["context"]
        tab.apply_appearance(payload["appearance"])
        self._plot_tabs.append(tab)
        if spec.is_layer_viewer:
            tab.layerChanged.connect(lambda L, t=tab: self._scrub_layer(t, L))
        tab.titleChanged.connect(lambda name, t=tab: self._on_plot_renamed(t, name))
        index = self._add_page(tab, tab.title, closable=True)
        self.tabbar.setCurrentIndex(index)
        self._feed_plot(tab, payload["raw"])  # shape via context + render
        win.close()  # fires closed -> _on_detached_closed drops the reference

    def _feed_plot(self, tab, raw_df) -> None:
        if tab not in self._plot_tabs:
            return  # closed before the query returned
        tab.raw = raw_df
        # Hover extras (part_id/layer) resolve through the rename map: a
        # self-contained tab uses its frozen one, a live tab the session's.
        ctx = getattr(tab, "context", None)
        tab.set_renames(ctx.get("renames", {}) if ctx else self.session.renames)
        tab.set_dataframe(self._shape_for(tab, raw_df))
        if tab is self._active_plot:  # data just arrived — refresh Min/Max etc.
            self.panel.sync_plot(tab.panel_state())

    def _shape_for(self, tab, raw_df):
        """Shape a plot's raw frame: a self-contained tab uses its frozen
        context; a session-linked tab follows the live session."""
        ctx = tab.context
        if ctx is not None:
            from . import derive
            return derive.shape(raw_df, ctx["derivations"], ctx["removed"],
                                ctx["row_filter"], ctx.get("renames"))
        return self.controller.shape_filtered(raw_df, tab.row_filter)

    def _reshape_plots(self) -> None:
        """Re-shape session-linked plots after a column change. Self-contained
        tabs (docked back from a floating window) are frozen to their own
        context and skipped, so a derivation edit never disturbs them."""
        for tab in self._plot_tabs:
            if tab.context is not None:
                continue
            if getattr(tab, "raw", None) is not None:
                tab.set_dataframe(
                    self.controller.shape_filtered(tab.raw, tab.row_filter)
                )

    def _start_rename_column(self) -> None:
        """Toolbar 'Rename column': rename the selected column, or arm
        click-to-rename if nothing is selected (handled by the grid)."""
        if self._data_tab is not None:
            self._data_tab.start_rename()

    def _rename_column(self, old: str, new: str) -> None:
        """Commit an inline column rename across the whole app: controller state
        (renames map / derivation names / references), open plots, the grid
        layout, and persistence."""
        self._run("rename", old=old, new=new)

    # -- column info panel (data tab) ----------------------------------
    def _open_column_panel(self, col: str) -> None:
        """Double-click on a column's cells → show its info in the side panel."""
        if self._data_tab is None:
            return
        info = self._data_tab.column_info(col)
        if info is None:
            return
        was_visible = self.panel.isVisible()
        self.panel.show_for("data")
        self.panel.show_column_info(info)
        self._panel_data_open = True
        self.panel.setVisible(True)
        if not was_visible:
            self._sync_toolbar(self.tabbar.currentIndex())  # reflect the toggle

    def _rename_column_from_panel(self, old: str, new: str) -> None:
        """Rename driven from the column-info panel's Name field, then refresh
        the panel to whatever name the column now has."""
        self._rename_column(old, new)
        if self._data_tab is None:
            return
        cur = new if new in self._data_tab.model.columns else old
        self.panel.show_column_info(self._data_tab.column_info(cur))

    def _set_column_sigfigs(self, col: str, n: int) -> None:
        if self._data_tab is not None:
            self._data_tab.set_column_sigfigs(col, n)

    def _on_column_selection(self, col: str) -> None:
        """When the column-info panel is open, follow the grid's selection."""
        if self._data_tab is None or not self.panel.isVisible():
            return
        widget = self.stack.currentWidget()
        if widget is None or widget.property("tabkind") != "data":
            return
        info = self._data_tab.column_info(col) if col else None
        self.panel.show_column_info(info)

    def _reset_selection(self) -> None:
        if self._data_tab is not None:
            self._data_tab.clear_selection()

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

        self._log = _ElidingLabel("Ready")
        self._log.setObjectName("StatusLog")
        sb.addWidget(self._log, 1)

        self._progress = QProgressBar()
        self._progress.setFixedWidth(170)
        self._progress.setVisible(False)
        sb.addWidget(self._progress)

        # Shown while a long background job (DBSCAN part assignment) runs.
        self._job_label = QLabel("")
        self._job_label.setStyleSheet("color: palette(highlight); font-weight: 600;")
        self._job_label.setVisible(False)
        sb.addPermanentWidget(self._job_label)

        # Shown only while a macro is being recorded.
        self._rec_label = QLabel("")
        self._rec_label.setStyleSheet("color: #d93025; font-weight: 600;")
        self._rec_label.setVisible(False)
        sb.addPermanentWidget(self._rec_label)

        self._log_btn = QToolButton()
        self._log_btn.setText("Show log")
        self._log_btn.setAutoRaise(True)
        self._log_btn.clicked.connect(self._open_log)
        sb.addPermanentWidget(self._log_btn)
        self._log_window = None

    def set_status(self, text: str, *, log: bool = True) -> None:
        self._log.setText(text)
        if log:  # log=False re-shows a line that is already in the log
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
        w = self.stack.currentWidget()
        if w is not None and w.property("tabkind") == "data":
            self._panel_data_open = False  # remember it's closed on Data
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
    def refresh_data_layers(self) -> None:
        """Re-bind the Data toolbar's layer selector to the controller's current
        available-layer set (e.g. after masking narrows which layers have data).
        A no-op unless the Data tab is the one on screen — the selector is rebuilt
        from the live set anyway the next time that tab is shown."""
        index = self.stack.currentIndex()
        widget = self.stack.widget(index)
        if widget is not None and widget.property("tabkind") == "data":
            self._sync_toolbar(index)

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
        else:  # data — restore the Data tab's own panel preference
            self.panel.setVisible(self._panel_data_open)
            if self._panel_data_open:
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
                layers=(self.controller.available_layers() or None),
                current_layer=self.session.current_layer,
                sidebar_open=self.panel.isVisible(),
                on_toggle_sidebar=self._toggle_sidebar,
                on_layer_changed=self._on_layer_changed,
                on_column_visibility=(
                    (lambda n, v: self._run("set_visible", name=n, visible=v))
                    if dt else None
                ),
                on_rename=self._start_rename_column,
                on_add_derive=self._add_derive_column,
                on_add_label=self._add_group_label,
                on_add_excel=self._add_excel_column,
                on_remove_column=self._remove_columns,
                on_restore_column=self._restore_column,
                on_reset_selection=self._reset_selection,
                has_parts=self.controller.has_part_assignment(),
                part_has_params=self.controller.has_laser_parameters(),
                on_part_calc=self._add_part_calc,
                on_part_params=self._add_laser_parameters,
                on_part_import=self._import_parts_csv,
                on_filter=self._on_filter,
                on_remove_filter=self._on_remove_last_filter,
                on_reset_filter=self._on_reset_filters,
                on_new_plot=lambda name=None: self._new_plot(name),
                on_export_excel=self._export_excel,
                recording=self.recorder.active,
                on_macro_record=self._toggle_macro_recording,
                on_macro_run=self._run_macro,
                recent_macros=[(macros.macro_name(p), p) for p in macros.recent()],
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
                on_title=lambda v: p and p.set_title_visible(v),
                on_screenshot=self._screenshot_plot,
                on_popout=self._popout_plot,
            )

    def _screenshot_plot(self) -> None:
        """Save the active plot to an image file (location + type via dialog)."""
        p = self._active_plot
        if p is None:
            return
        from pathlib import Path
        from PyQt6.QtWidgets import QFileDialog, QMessageBox

        safe = "".join(
            c if (c.isalnum() or c in " -_") else "_" for c in p.title
        ).strip() or "plot"
        start = str(Path.home() / f"{safe}.png")
        path, selected = QFileDialog.getSaveFileName(
            self, "Save plot image", start,
            "PNG image (*.png);;JPEG image (*.jpg *.jpeg);;"
            "Bitmap (*.bmp);;TIFF image (*.tif *.tiff)",
        )
        if not path:
            return
        if not Path(path).suffix:  # user typed a bare name — honour the filter
            path += {
                "JPEG image (*.jpg *.jpeg)": ".jpg",
                "Bitmap (*.bmp)": ".bmp",
                "TIFF image (*.tif *.tiff)": ".tif",
            }.get(selected, ".png")
        if p.save_image(path):
            self.statusBar().showMessage(f"Saved {Path(path).name}", 4000)
        else:
            QMessageBox.warning(self, "Screenshot",
                                "Couldn't save the plot image.")

    def _on_layer_changed(self, layer: int) -> None:
        self.controller.show_layer(layer)

    def _on_filter(self) -> None:
        dt = self._data_tab
        if dt is None:
            return
        from .filter_dialog import FilterConditionDialog

        dlg = FilterConditionDialog(dt._columns, self,
                                    renames=self.session.renames)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._run("filter_add", condition=dlg.condition())

    def _edit_filter_at(self, index: int) -> None:
        dt = self._data_tab
        conditions = self.controller.filters()
        if dt is None or not (0 <= index < len(conditions)):
            return
        from .filter_dialog import FilterConditionDialog

        dlg = FilterConditionDialog(dt._columns, self, initial=conditions[index],
                                    renames=self.session.renames)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._run("filter_edit", index=index, condition=dlg.condition())

    def _remove_filter_at(self, index: int) -> None:
        self._run("filter_remove", index=index)

    def _on_remove_last_filter(self) -> None:
        self._run("filter_remove_last")

    def _on_reset_filters(self) -> None:
        self._run("filter_reset")

    def _add_derive_column(self) -> None:
        dt = self._data_tab
        if dt is None:
            return
        from .derive_dialog import DeriveColumnDialog

        taken = [d["name"] for d in self.session.derivations]
        dlg = DeriveColumnDialog(dt._columns, self, taken=taken,
                                 renames=self.session.renames)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, expr, group = dlg.result_values()
        overwrite = dlg.is_overwrite()
        after = dlg.after_column()
        self._run("derive", name=name, expr=expr, group=group,
                  overwrite=overwrite, after=after or "")

    def _add_group_label(self) -> None:
        dt = self._data_tab
        if dt is None:
            return
        from .label_dialog import GroupLabelDialog

        taken = [d["name"] for d in self.session.derivations]
        dlg = GroupLabelDialog(dt._columns, self, taken=taken,
                               renames=self.session.renames)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, rules, default = dlg.result_values()
        self._run("label", name=name, rules=rules, default=default)

    def _add_excel_column(self) -> None:
        dt = self._data_tab
        if dt is None:
            return
        from .excel_dialog import ExcelImportDialog

        taken = [d["name"] for d in self.session.derivations]
        dlg = ExcelImportDialog(dt._columns, self, taken=taken)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, grid_key, mapping, dtype, _n = dlg.result_values()
        self._run("excel_import", name=name, key=grid_key, mapping=mapping,
                  dtype=dtype, source=dlg.source_values())

    # -- contextual part-wise actions ----------------------------------
    def _add_part_calc(self) -> None:
        """Quick per-part calculation → a derived column reduced by part_id
        (CoV lays out mean / std / ratio as one action)."""
        dt = self._data_tab
        if dt is None:
            return
        from .part_calc_dialog import PartCalcDialog

        pid = self.controller.part_id_display()  # rename-aware part column
        taken = [d["name"] for d in self.session.derivations]
        dlg = PartCalcDialog(dt._columns, pid, self, taken=taken)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, signal, reducer = dlg.result_values()
        self._run("part_calc", signal=signal, reducer=reducer, name=name)

    def _add_laser_parameters(self) -> None:
        """Join the QuantAM per-part scan-volume laser parameters onto the grid."""
        if self._data_tab is not None:
            self._run("laser_params")

    def _import_parts_csv(self) -> None:
        """Open the parts-CSV section picker and join the staged columns onto the
        grid (one action, however many columns)."""
        from .import_parts_dialog import ImportPartsCSVDialog

        if self._data_tab is None:
            return
        try:
            sections = self.controller.parts_csv_sections()
        except Exception as exc:  # noqa: BLE001 — surfaced, non-fatal
            self.set_status(f"Couldn't read the parts CSV: {exc}")
            return
        if not sections:
            self.set_status("The parts CSV has no importable sections.")
            return
        dlg = ImportPartsCSVDialog(sections, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        staged = dlg.result_values()  # [(section, column)]
        if staged:
            self._run("parts_csv_import", items=[list(s) for s in staged])

    def _export_excel(self) -> None:
        dt = self._data_tab
        if dt is None or self.session.result is None:
            self.set_status("Load a build before exporting.")
            return
        from .export_dialog import ExcelExportDialog

        store = self.session.store
        dlg = ExcelExportDialog(
            dt._columns, self,
            layers=list(store.layers) if store is not None else [],
            current_layer=self.session.current_layer,
            renames=self.session.renames,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        spec = dlg.result_values()
        self._start_export(spec)
        # An output, not an undo step — but a macro being recorded keeps it
        # (what to write, never where: a run asks for the file).
        from pathlib import Path

        self.actions.note(
            "export_excel", mode=spec["mode"], scope=list(spec["scope"]),
            sheet=spec["sheet"], respect_filters=spec["respect_filters"],
            key=spec.get("key"), values=[list(v) for v in spec.get("values") or []],
            columns=spec.get("columns"), path=spec["path"],
            filename=Path(spec["path"]).name)

    def _start_export(self, spec, state=None) -> None:
        """Query the export's span and write the file. ``state`` (a shaping
        snapshot) pins what is written to the data as it stood when the export
        was asked for — a macro's later steps must not change it."""
        mode, lo, hi = spec["scope"]
        if mode == "current":  # the layer on screen -> a single-layer query
            cur = self.session.current_layer
            qmode, qlo, qhi = "single", cur, cur
        else:
            qmode, qlo, qhi = mode, lo, hi
        self.set_status("Exporting…")
        self.controller.query_for(
            qmode, qlo, qhi,
            lambda raw, s=spec, st=state: self._write_export(s, raw, st)
        )

    def _shape_as(self, state, raw_df, filters):
        """Shape ``raw_df`` as the data stood in ``state`` (derived / removed /
        renamed columns), then put the live state back."""
        s = self.session
        live = (s.derivations, s.removed, s.renames)
        s.derivations, s.removed, s.renames = (
            state["derivations"], state["removed"], state["renames"])
        try:
            return self.controller.shape_filtered(raw_df, filters)
        finally:
            s.derivations, s.removed, s.renames = live

    def _write_export(self, spec, raw_df, state=None) -> None:
        from pathlib import Path

        from . import export

        try:
            if state is not None:
                frame = self._shape_as(
                    state, raw_df,
                    state["filters"] if spec["respect_filters"] else [])
            else:
                filters = (self.controller.filters()
                           if spec["respect_filters"] else [])
                frame = self.controller.shape_filtered(raw_df, filters)
            if spec["mode"] == "summary":
                out = export.build_summary(frame, spec["key"], spec["values"])
            else:
                out = export.build_raw(frame, spec.get("columns"))
            n = export.write_xlsx(out, spec["path"], spec["sheet"])
        except Exception as exc:  # noqa: BLE001 - report, don't crash
            self.set_status(f"Export failed: {exc}")
            return
        self.set_status(f"Exported {n} row(s) to {Path(spec['path']).name}.")

    def _remove_columns(self) -> None:
        dt = self._data_tab
        if dt is None:
            return
        names = dt.selected_columns()
        if not names:
            self.set_status("Select a column (click its header) to remove.")
            return
        self._run("remove", names=names)

    def _restore_column(self, name: str) -> None:
        self._run("restore", name=name)

    # -- action layer / undo-redo --------------------------------------
    def _run(self, op: str, **params):
        """Perform a user action through the action layer (which snapshots for
        undo, persists and re-shapes plots) and report its outcome."""
        out = self.actions.run(op, **params)
        if out.message:
            self.set_status(out.message)
        return out

    def _undo(self) -> None:
        label = self.actions.undo()
        if label:
            self.set_status(f"Undid: {label}.")

    def _redo(self) -> None:
        label = self.actions.redo()
        if label:
            self.set_status(f"Redid: {label}.")

    def _after_restore(self) -> None:
        """An undo/redo just put a saved state back: persist it and rebuild the
        Data toolbar so its menus (show/hide, restore column) match."""
        self._save_ui()
        self._last_columns = (
            list(self._data_tab._columns) if self._data_tab is not None else None)
        self.refresh_data_layers()

    def _sync_history_buttons(self) -> None:
        h = self.actions.history
        for key, can, label, word, keys in (
            ("undo", h.can_undo(), h.undo_label(), "Undo", "Ctrl+Z"),
            ("redo", h.can_redo(), h.redo_label(), "Redo", "Ctrl+Shift+Z"),
        ):
            btn = self._global_btns[key]
            btn.setEnabled(can)
            btn.setToolTip(f"{word}: {label} ({keys})" if can else f"{word} ({keys})")

    def set_background_job(self, text: str | None) -> None:
        """Show (or clear, with None) a standing note in the status bar for a
        long job that runs behind the app — ordinary status messages come and
        go without hiding it."""
        self._job_label.setText(text or "")
        self._job_label.setVisible(bool(text))

    def _reset_history(self) -> None:
        """A build was loaded / set up / rebuilt: the undo history starts over,
        and a macro recording in progress can't continue across builds."""
        if self.recorder.active:
            self.recorder.cancel()
            self.set_status("Macro recording stopped (the build changed) — "
                            "nothing was saved.")
        self.actions.reset()

    # -- macros ----------------------------------------------------------
    def _macro_start_dir(self) -> str:
        from pathlib import Path

        return self._macro_dir or str(Path.home())

    def _on_recorder_changed(self) -> None:
        """Keep the status-bar indicator current; swap the toolbar's Record /
        Stop button when recording starts or ends."""
        rec = self.recorder
        n = rec.count()
        self._rec_label.setText(
            f"● Recording macro — {n} step{'s' if n != 1 else ''}")
        self._rec_label.setVisible(rec.active)
        if rec.active != self._rec_was_active:
            self._rec_was_active = rec.active
            self.refresh_data_layers()  # rebuilds the Data toolbar if showing

    def _toggle_macro_recording(self) -> None:
        if not self.recorder.active:
            self.recorder.start()
            self.set_status("Recording a macro — perform the actions, then "
                            "press Stop to save it.")
            return
        steps = self.recorder.stop()
        if not steps:
            self.set_status("Nothing was recorded.")
            return
        self._save_recording(steps)

    def _save_recording(self, steps: list) -> None:
        from pathlib import Path
        from PyQt6.QtWidgets import QFileDialog

        from .message_dialog import ask, tell

        n = len(steps)
        while True:
            start = str(Path(self._macro_start_dir()) / f"macro{macros.SUFFIX}")
            path, _sel = QFileDialog.getSaveFileName(
                self, "Save macro", start, macros.FILE_FILTER)
            if not path:
                if ask(self, "Discard the recording?",
                       f"The {n} recorded step{'s' if n != 1 else ''} will be lost.",
                       ok_text="Discard", cancel_text="Save…"):
                    self.set_status("Macro recording discarded.")
                    return
                continue
            try:
                out = macros.save(path, macros.macro_name(path), steps)
            except OSError as exc:
                tell(self, "Couldn't save the macro", str(exc))
                continue
            self._macro_dir = str(out.parent)
            self._remember_macro(out)
            self.set_status(
                f"Saved macro '{macros.macro_name(out)}' "
                f"({n} step{'s' if n != 1 else ''}) to {out.name}.")
            return

    def _remember_macro(self, path) -> None:
        """Add a macro file to the recent list and refresh the Run menu. The
        toolbar rebuild is deferred: this can be reached from that menu itself."""
        from PyQt6.QtCore import QTimer

        macros.remember(path)
        QTimer.singleShot(0, self.refresh_data_layers)

    def _run_macro(self, path: str | None = None) -> None:
        """Run a macro — ``path`` from the recent list, or picked from a file
        dialog: check it, preview its steps, then run them as one all-or-nothing
        action (a single undo step)."""
        from pathlib import Path
        from PyQt6.QtWidgets import QFileDialog

        from .macro_dialog import MacroIssuesDialog, MacroPreviewDialog

        if self._data_tab is None or self.session.result is None:
            self.set_status("Load a build before running a macro.")
            return
        if not path:
            path, _sel = QFileDialog.getOpenFileName(
                self, "Run macro", self._macro_start_dir(), macros.FILE_FILTER)
            if not path:
                return
        self._macro_dir = str(Path(path).parent)
        try:
            name, steps = macros.load(path)
        except macros.MacroError as exc:
            MacroIssuesDialog(macros.macro_name(path), [str(exc)], self).exec()
            return
        self._remember_macro(path)
        # Describe the steps under this build's column names.
        descs = [
            macros.describe(s["op"], macros.resolve(
                s["op"], s["params"], self.session.renames))
            for s in steps
        ]
        # Check the WHOLE macro against this build before anything changes, and
        # list every problem at once.
        found = self.actions.check_batch(
            [(s["op"], s["params"]) for s in steps], macros.resolve)
        if found:
            by_step: dict[int, list[str]] = {}
            for i, msg in found:
                by_step.setdefault(i, []).append(msg)
            MacroIssuesDialog(name, [
                f"Step {i + 1} — {descs[i]}\n" + "\n".join(f"   • {m}" for m in msgs)
                for i, msgs in sorted(by_step.items())
            ], self).exec()
            self.set_status(
                f"Macro '{name}' was not run — {len(by_step)} step"
                f"{'s have' if len(by_step) != 1 else ' has'} issues.")
            return
        if MacroPreviewDialog(name, descs, self).exec() != QDialog.DialogCode.Accepted:
            return
        # Excel steps carry no data, and exports no destination — each asks for
        # its file before anything runs.
        prepared = []
        for i, s in enumerate(steps):
            params = dict(s["params"])
            if s["op"] == "export_excel":
                target = self._macro_export_step(i, params)
                if target is None:
                    self.set_status("Macro cancelled.")
                    return
                params["path"] = target
            if s["op"] == "excel_import":
                issue = self._macro_excel_step(i, params)
                if issue is None:
                    self.set_status("Macro cancelled.")
                    return
                if issue:
                    MacroIssuesDialog(
                        name, [f"Step {i + 1} — {descs[i]}\n   • {issue}"], self
                    ).exec()
                    return
            prepared.append((s["op"], params))
        failed, message, notes = self.actions.run_batch(
            f"Run macro '{name}'", prepared,
            prepare=lambda op, p: macros.resolve(op, p, self.session.renames))
        if failed is not None:
            MacroIssuesDialog(
                name, [f"Step {failed + 1} — {descs[failed]}\n   • {message}"], self
            ).exec()
            self.set_status(f"Macro '{name}' was not run — see the issues.")
            return
        n = len(steps)
        self.set_status(
            f"Ran macro '{name}' ({n} step{'s' if n != 1 else ''})."
            + "".join(f" {note}" for note in notes))

    def _macro_export_step(self, index: int, params: dict):
        """Ask where a macro's Excel-export step should save. Returns the path,
        or None if the user cancelled."""
        from pathlib import Path
        from PyQt6.QtWidgets import QFileDialog

        start = str(Path(self._macro_start_dir())
                    / (params.get("filename") or "export.xlsx"))
        path, _sel = QFileDialog.getSaveFileName(
            self, f"Macro step {index + 1}: save the Excel export as",
            start, "Excel workbook (*.xlsx)")
        if not path:
            return None
        return path if path.lower().endswith(".xlsx") else path + ".xlsx"

    def _macro_excel_step(self, index: int, params: dict):
        """Ask for the Excel file behind a macro's import step and read the
        recorded sheet / columns from it into ``params``. Returns "" on success,
        an issue message, or None if the user cancelled."""
        from pathlib import Path
        from PyQt6.QtWidgets import QFileDialog

        from .excel_dialog import parse_mapping

        src = params.get("source") or {}
        sheet, key_h, val_h = (src.get("sheet"), src.get("key_column"),
                               src.get("value_column"))
        if not (sheet and key_h and val_h):
            return "The step doesn't say which sheet and columns to read."
        path, _sel = QFileDialog.getOpenFileName(
            self,
            f"Macro step {index + 1}: Excel file for column '{params.get('name')}'",
            self._macro_start_dir(), "Excel workbook (*.xlsx *.xlsm)")
        if not path:
            return None
        try:
            mapping, dtype, _n = parse_mapping(path, sheet, key_h, val_h)
        except Exception as exc:  # noqa: BLE001 — unreadable file etc. → an issue
            return f"{Path(path).name}: {exc}"
        if not mapping:
            return f"{Path(path).name}: no usable key/value rows in '{sheet}'."
        params["mapping"], params["dtype"] = mapping, dtype
        return ""

    def _toggle_sidebar(self, checked: bool) -> None:
        kind = self.stack.currentWidget().property("tabkind")
        if kind == "data":  # remember the Data tab's own choice
            self._panel_data_open = checked
        if checked:
            self.panel.show_for(kind)
            self.panel.setVisible(True)
        else:
            self.panel.setVisible(False)

    # -- shutdown ------------------------------------------------------
    def closeEvent(self, event) -> None:
        self.controller.shutdown()  # stop any running worker thread
        super().closeEvent(event)
