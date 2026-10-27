"""File tab — the backstage, modelled on PowerPoint's File view.

Full-window takeover (no per-tab toolbar). Left sidebar of file actions; a main
area that stacks a Start page (primary tiles + Recent/Favourites/Search) and a
DataStore page. The DataStore entry appears dynamically once a build is loaded
— the backstage is where the parquet-cache definition (columns, ranges, bounds,
pipeline) is created and rebuilt.

Inert except for *structural* navigation signals the main window uses:
``loadRequested``, ``createExcelRequested``, and ``datastoreCreateRequested``.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import icons
from .datastore_settings import DataStoreSettings

# Placeholder recent items, purely so the strip looks real while unwired.
_RECENT = [
    "JR299  ·  packet  ·  just now",
    "JR295  ·  packet  ·  2h ago",
    "JR324  ·  packet  ·  yesterday",
    "Untitled  ·  CSV only  ·  3 days ago",
]


def _tile(title: str, subtitle: str) -> QPushButton:
    btn = QPushButton()
    btn.setProperty("class", "Tile")
    btn.setMinimumSize(260, 120)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    lay = QVBoxLayout(btn)
    lay.setContentsMargins(18, 16, 18, 16)
    t = QLabel(title)
    t.setProperty("class", "TileTitle")
    s = QLabel(subtitle)
    s.setProperty("class", "TileSub")
    s.setWordWrap(True)
    lay.addWidget(t)
    lay.addWidget(s)
    lay.addStretch(1)
    return btn


class Backstage(QWidget):
    newRequested = pyqtSignal()       # prepare a fresh build
    openRequested = pyqtSignal()      # open a build that already has a cache
    createExcelRequested = pyqtSignal()
    datastoreBuildRequested = pyqtSignal()  # Build/Rebuild on the setup page

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Backstage")
        self.setProperty("tabkind", "file")

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_sidebar())
        root.addWidget(self._build_main(), 1)

    # -- left sidebar --------------------------------------------------
    def _build_sidebar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("BackstageSidebar")
        bar.setFixedWidth(210)
        lay = QVBoxLayout(bar)
        lay.setContentsMargins(0, 12, 0, 12)
        lay.setSpacing(0)

        def add(text: str, *, primary: bool = False) -> QPushButton:
            b = QPushButton(text)
            if primary:
                b.setProperty("primary", "true")
            lay.addWidget(b)
            return b

        self.btn_new = add("New", primary=True)
        self.btn_open = add("Open", primary=True)
        self.btn_excel = add("Create Excel from AMPM", primary=True)
        lay.addSpacing(8)
        # Appears only once a build is loaded.
        self.btn_datastore = add("DataStore")
        self.btn_datastore.setVisible(False)
        self.btn_export = add("Export")
        self.btn_info = add("Info")
        lay.addStretch(1)
        self.btn_close = add("Close")

        self.btn_new.clicked.connect(self.newRequested)
        self.btn_open.clicked.connect(self.openRequested)
        self.btn_excel.clicked.connect(self.createExcelRequested)
        self.btn_datastore.clicked.connect(self.show_datastore_page)
        return bar

    # -- main area (stacked: Start / DataStore) ------------------------
    def _build_main(self) -> QWidget:
        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        self.main_stack = QStackedWidget()
        outer.addWidget(self.main_stack)
        self.main_stack.addWidget(self._start_page())       # index 0
        self.main_stack.addWidget(self._datastore_page())   # index 1
        return container

    def _start_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(32, 28, 32, 28)
        lay.setSpacing(18)

        heading = QLabel("Start")
        heading.setProperty("class", "SectionHeading")
        lay.addWidget(heading)

        # Primary tiles (where PowerPoint puts templates).
        tiles = QHBoxLayout()
        tiles.setSpacing(16)
        self.tile_new = _tile(
            "New", "Prepare a fresh build: detect inputs and build its DataStore."
        )
        self.tile_open = _tile(
            "Open", "Open a build that already has a DataStore and explore it."
        )
        self.tile_excel = _tile(
            "Create Excel from AMPM",
            "Generate samples-template workbooks from a build directory.",
        )
        self.tile_new.clicked.connect(self.newRequested)
        self.tile_open.clicked.connect(self.openRequested)
        self.tile_excel.clicked.connect(self.createExcelRequested)
        tiles.addWidget(self.tile_new)
        tiles.addWidget(self.tile_open)
        tiles.addWidget(self.tile_excel)
        tiles.addStretch(1)
        lay.addLayout(tiles)

        lay.addWidget(self._divider())

        # Recent / Favourites / Search strip.
        strip = QHBoxLayout()
        strip.setSpacing(8)
        self.grp = QButtonGroup(self)
        for i, name in enumerate(("Recent", "Favourites", "Shared with Me")):
            b = QPushButton(name)
            b.setCheckable(True)
            if i == 0:
                b.setChecked(True)
            self.grp.addButton(b)
            strip.addWidget(b)
        strip.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search for a file")
        self.search.setFixedWidth(280)
        strip.addWidget(self.search)
        lay.addLayout(strip)

        self.recent = QListWidget()
        self.recent.addItems(_RECENT)
        lay.addWidget(self.recent, 1)
        return page

    def _datastore_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(32, 28, 32, 28)
        lay.setSpacing(10)

        heading = QLabel("DataStore")
        heading.setProperty("class", "SectionHeading")
        lay.addWidget(heading)
        sub = QLabel(
            "Build the parquet cache for this build. Mask / assign-parts / "
            "correction are applied later from the Data toolbar."
        )
        sub.setProperty("class", "TileSub")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.ds_form = DataStoreSettings()
        self.ds_form.buildRequested.connect(self.datastoreBuildRequested)
        scroll.setWidget(self.ds_form)
        lay.addWidget(scroll, 1)
        return page

    def _divider(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        return line

    # -- state / navigation --------------------------------------------
    def set_build_loaded(self, loaded: bool) -> None:
        self.btn_datastore.setVisible(loaded)
        if not loaded:
            self.show_start_page()

    def show_datastore_page(self) -> None:
        self.main_stack.setCurrentIndex(1)

    def show_start_page(self) -> None:
        self.main_stack.setCurrentIndex(0)

    def set_datastore_exists(self, exists: bool) -> None:
        self.ds_form.set_exists(exists)

    def set_datastore_config(
        self, config: dict, layers: list[int], columns: list[str] | None = None
    ) -> None:
        self.ds_form.set_config(config, layers, columns)

    def set_loading(self, loading: bool) -> None:
        """Disable the load entry points while a load is in flight."""
        for w in (self.btn_new, self.btn_open, self.tile_new, self.tile_open):
            w.setEnabled(not loading)

    def apply_icons(self, color: str) -> None:
        """(Re)tint the sidebar icons for the active theme."""
        mapping = {
            self.btn_new: "load_packet",
            self.btn_open: "open",
            self.btn_excel: "create_excel",
            self.btn_datastore: "datastore",
            self.btn_export: "export",
            self.btn_info: "info",
            self.btn_close: "close",
        }
        for button, name in mapping.items():
            button.setIcon(icons.ui(name, color))
