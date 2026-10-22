"""The main window: tab strip, context-swapping toolbar, dock, status bar.

Only *structural* navigation is wired — opening the Data tab, spawning Plot
tabs, swapping the toolbar/dock per active tab, and the status helpers. All the
actual data and plot actions are inert, to be connected in a later pass.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QLabel,
    QMainWindow,
    QProgressBar,
    QStatusBar,
    QTabBar,
    QTabWidget,
    QToolBar,
    QToolButton,
    QWidget,
)

from . import toolbars
from .backstage import Backstage
from .data_tab import DataTab
from .dock import Dock
from .plot_tab import PlotTab

APP_TITLE = "AMPM Analyzer"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1300, 820)

        # Central tab strip (view switcher).
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(False)
        self.tabs.setDocumentMode(True)
        self.setCentralWidget(self.tabs)

        # Context-swapping toolbar (contents rebuilt per active tab).
        self.toolbar = QToolBar("Main")
        self.toolbar.setMovable(False)
        self.toolbar.setFloatable(False)
        self.addToolBar(self.toolbar)

        # Side dock (repopulates per view).
        self.dock = Dock(self)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)

        self._init_statusbar()

        # "+" corner button -> new Plot tab.
        plus = QToolButton()
        plus.setText("+")
        plus.setToolTip("New plot")
        plus.clicked.connect(lambda: self._new_plot_tab())
        self.tabs.setCornerWidget(plus, Qt.Corner.TopRightCorner)

        # File (backstage) tab — pinned left-most, non-closable.
        self.backstage = Backstage()
        self.backstage.loadRequested.connect(self._open_data_tab)
        self.backstage.createExcelRequested.connect(
            lambda: self.set_status("Create Excel from AMPM — not wired yet")
        )
        self.tabs.addTab(self.backstage, "File")
        self._lock_tab(0)

        self._data_tab: DataTab | None = None

        self.tabs.currentChanged.connect(self._sync_toolbar)
        self.tabs.tabCloseRequested.connect(self._close_tab)

        self._sync_toolbar(self.tabs.currentIndex())
        self.set_status("Ready")

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

    # -- tab helpers ---------------------------------------------------
    def _lock_tab(self, index: int) -> None:
        """Remove the close button so this tab can't be closed."""
        bar = self.tabs.tabBar()
        for pos in (
            QTabBar.ButtonPosition.RightSide,
            QTabBar.ButtonPosition.LeftSide,
        ):
            btn = bar.tabButton(index, pos)
            if btn is not None:
                btn.deleteLater()
            bar.setTabButton(index, pos, None)

    def _open_data_tab(self) -> None:
        if self._data_tab is None:
            self._data_tab = DataTab()
            index = self.tabs.insertTab(1, self._data_tab, "Data")
            self._lock_tab(index)  # one Data tab; close the packet via File
        self.tabs.setCurrentWidget(self._data_tab)

    def _new_plot_tab(self, title: str | None = None) -> None:
        if self._data_tab is None:
            self._open_data_tab()
        tab = PlotTab(title)
        index = self.tabs.addTab(tab, tab.title)
        self.tabs.setCurrentIndex(index)

    def _close_tab(self, index: int) -> None:
        widget = self.tabs.widget(index)
        if widget is not None and widget.property("tabkind") == "plot":
            self.tabs.removeTab(index)
            widget.deleteLater()

    # -- toolbar swap --------------------------------------------------
    def _sync_toolbar(self, index: int) -> None:
        widget: QWidget | None = self.tabs.widget(index)
        kind = widget.property("tabkind") if widget is not None else "file"

        self.toolbar.clear()
        if kind == "file":
            self.toolbar.hide()
            self.dock.hide()
            return

        self.toolbar.show()
        self.dock.show()
        if kind == "data":
            toolbars.populate_data(self.toolbar)
        else:
            toolbars.populate_plot(self.toolbar)
        self.dock.show_for(kind)
