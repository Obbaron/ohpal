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

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
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

from . import toolbars
from .backstage import Backstage
from .data_tab import DataTab
from .dock import SidePanel
from .plot_tab import PlotTab

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

        self._plus = QToolButton()
        plus = self._plus
        plus.setText("+")
        plus.setAutoRaise(True)
        plus.setToolTip("New plot")
        plus.setVisible(False)  # only shown once off the File tab
        plus.clicked.connect(lambda: self._new_plot_tab())

        tab_row = QWidget()
        tab_row.setObjectName("TabRow")
        row = QHBoxLayout(tab_row)
        row.setContentsMargins(4, 2, 4, 0)
        row.setSpacing(2)
        row.addWidget(self.tabbar)
        row.addWidget(plus)
        row.addStretch(1)
        root.addWidget(tab_row)

        # Context-swapping toolbar — now a plain widget in the layout, below the
        # tab strip. Contents rebuilt per active tab.
        self.toolbar = QToolBar("Main")
        self.toolbar.setMovable(False)
        self.toolbar.setFloatable(False)
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

        # File (backstage) tab — pinned left-most, non-closable.
        self.backstage = Backstage()
        self.backstage.loadRequested.connect(self._open_data_tab)
        self.backstage.createExcelRequested.connect(
            lambda: self.set_status("Create Excel from AMPM — not wired yet")
        )
        self.backstage.datastoreCreateRequested.connect(self._on_datastore_created)
        self._add_page(self.backstage, "File", closable=False)

        self._data_tab: DataTab | None = None

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

    def _open_data_tab(self) -> None:
        first_load = self._data_tab is None
        if first_load:
            self._data_tab = DataTab()
            self._insert_page(1, self._data_tab, "Data", closable=False)
            self.backstage.set_build_loaded(True)  # reveal the DataStore entry
        self._select_widget(self._data_tab)
        if first_load:
            self._prompt_datastore()

    def _prompt_datastore(self) -> None:
        """On first load with no cache, offer to create a DataStore."""
        from PyQt6.QtWidgets import QMessageBox

        choice = QMessageBox.question(
            self,
            "DataStore",
            "No datastore exists for this build.\n\nWould you like to create one?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if choice == QMessageBox.StandardButton.Yes:
            self.backstage.show_datastore_page()
            self.tabbar.setCurrentIndex(0)  # to File, to configure the store
        else:
            self.set_status("No datastore — create one from File → DataStore to plot")

    def _on_datastore_created(self) -> None:
        self.backstage.set_datastore_exists(True)
        if self._data_tab is not None:
            self._select_widget(self._data_tab)
        self.set_status("DataStore created — not wired yet")

    def _new_plot_tab(self, title: str | None = None) -> None:
        if self._data_tab is None:
            self._open_data_tab()
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

    # -- toolbar swap --------------------------------------------------
    def _sync_toolbar(self, index: int) -> None:
        widget: QWidget | None = self.stack.widget(index)
        kind = widget.property("tabkind") if widget is not None else "file"

        self._plus.setVisible(kind != "file")  # no "+" on the backstage

        # Panel: hidden by default, auto-opens only where there's relevant
        # content (currently the Plot tab). Switching tabs re-evaluates it, so
        # a panel the user closed reopens when they return to a plot.
        if self.panel.has_content_for(kind):
            self.panel.show_for(kind)
            self.panel.setVisible(True)
        else:
            self.panel.setVisible(False)

        self.toolbar.clear()
        if kind == "file":
            self.toolbar.hide()
            return

        self.toolbar.show()
        if kind == "data":
            toolbars.populate_data(self.toolbar)
        else:
            toolbars.populate_plot(self.toolbar)
