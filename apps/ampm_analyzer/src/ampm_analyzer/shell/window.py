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

from . import icons, theme, toolbars
from .backstage import Backstage
from .controller import AppController
from .data_tab import DataTab
from .dock import SidePanel
from .plot_tab import PlotTab
from .state import BuildSession

APP_TITLE = "AMPM Analyzer"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1300, 820)

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
        self.panel.setVisible(False)  # hidden by default; opens when relevant

        content = QSplitter(Qt.Orientation.Horizontal)
        content.addWidget(self.stack)
        content.addWidget(self.panel)
        content.setStretchFactor(0, 1)
        content.setStretchFactor(1, 0)
        content.setCollapsible(0, False)
        content.setCollapsible(1, True)
        content.setSizes([1040, 260])
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
        self.backstage.createExcelRequested.connect(
            lambda: self.set_status("Create Excel from AMPM — not wired yet")
        )
        self.backstage.datastoreBuildRequested.connect(self._on_build_requested)
        self.backstage.apply_icons(color)
        self._add_page(self.backstage, "File", closable=False)

        self._data_tab: DataTab | None = None

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
            self._insert_page(1, self._data_tab, "Data", closable=False)
            self.backstage.set_build_loaded(True)  # reveal the DataStore entry
        return self._data_tab

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
        self._stats["build"].setText(f"build: {self.session.build_name}")
        self.backstage.set_build_loaded(True)

    def _on_setup_required(self, payload) -> None:
        config, layers, columns, exists = payload
        self.backstage.set_loading(False)
        self.show_progress(False)
        self.backstage.set_datastore_config(config, layers, columns)
        self.backstage.set_datastore_exists(exists)
        self.backstage.show_datastore_page()
        self.tabbar.setCurrentIndex(0)  # File tab
        self.set_status("Set up the DataStore, then Build.")

    def _on_build_requested(self) -> None:
        scope = self.backstage.ds_form.scope()
        self.controller.build_datastore(scope)

    def _on_cache_progress(self, done: int, total: int, layer: int) -> None:
        self._progress.setRange(0, total)
        self._progress.setValue(done)
        self._progress.setVisible(True)
        self.set_status(f"Building cache: layer {layer} ({done}/{total})")

    def _on_query_ready(self, result) -> None:
        self.backstage.set_loading(False)
        self.show_progress(False)
        self._ensure_data_tab()
        self._select_widget(self._data_tab)
        self._data_tab.set_dataframe(result.df)
        lo, hi = result.layers
        self._stats["points"].setText(f"points: {result.total_rows:,}")
        self._stats["drawn"].setText(f"drawn: {result.shown_rows:,}")
        capped = (
            f" (showing first {result.shown_rows:,})"
            if result.shown_rows < result.total_rows
            else ""
        )
        self.set_status(
            f"Loaded layer {lo}: {result.total_rows:,} rows{capped}"
        )

    def _on_load_failed(self, message: str) -> None:
        self.backstage.set_loading(False)
        self.show_progress(False)
        first_line = message.strip().splitlines()[-1] if message.strip() else message
        self.set_status(f"Load failed: {first_line}")

    def _new_plot_tab(self, title: str | None = None) -> None:
        self._ensure_data_tab()
        tab = PlotTab(title)
        index = self._add_page(tab, tab.title, closable=True)
        self.tabbar.setCurrentIndex(index)

    def _close_tab(self, index: int) -> None:
        widget = self.stack.widget(index)
        if widget is not None and widget.property("tabkind") == "plot":
            self.tabbar.removeTab(index)
            self.stack.removeWidget(widget)
            widget.deleteLater()

    def _on_tab_changed(self, index: int) -> None:
        if 0 <= index < self.stack.count():
            self.stack.setCurrentIndex(index)
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

        self._stats: dict[str, QLabel] = {}
        for key, text in (
            ("build", "build: —"),
            ("points", "points: —"),
            ("drawn", "drawn: —"),
            ("selected", "sel: 0"),
        ):
            lab = QLabel(text)
            lab.setProperty("class", "StatChip")
            sb.addPermanentWidget(lab)
            self._stats[key] = lab

    def set_status(self, text: str) -> None:
        self._log.setText(text)

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
            toolbars.populate_data(
                self.toolbar,
                color=color,
                columns=self._data_tab._columns if self._data_tab else None,
                sidebar_open=self.panel.isVisible(),
                on_toggle_sidebar=self._toggle_sidebar,
                on_new_plot=lambda name=None: self._new_plot_tab(name),
            )
        else:
            toolbars.populate_plot(self.toolbar, color=color)

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
