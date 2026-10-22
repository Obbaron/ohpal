"""File tab — the backstage, modelled on PowerPoint's File view.

Full-window takeover (no per-tab toolbar). Left sidebar of file actions, a main
area with the two primary action tiles and a Recent / Favourites / Search strip.

Inert except for two *structural* navigation signals the main window uses to
move between surfaces: ``loadRequested`` and ``createExcelRequested``.
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
    QVBoxLayout,
    QWidget,
)

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
    loadRequested = pyqtSignal()
    createExcelRequested = pyqtSignal()

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

        self.btn_load = add("Load packet data", primary=True)
        self.btn_excel = add("Create Excel from AMPM", primary=True)
        lay.addSpacing(8)
        self.btn_open = add("Open")
        self.btn_export = add("Export")
        self.btn_info = add("Info")
        lay.addStretch(1)
        self.btn_close = add("Close")

        # Structural navigation only (lets you move off the backstage).
        self.btn_load.clicked.connect(self.loadRequested)
        self.btn_open.clicked.connect(self.loadRequested)
        self.btn_excel.clicked.connect(self.createExcelRequested)
        return bar

    # -- main area -----------------------------------------------------
    def _build_main(self) -> QWidget:
        main = QWidget()
        lay = QVBoxLayout(main)
        lay.setContentsMargins(32, 28, 32, 28)
        lay.setSpacing(18)

        heading = QLabel("Start")
        heading.setProperty("class", "SectionHeading")
        lay.addWidget(heading)

        # Two primary tiles (where PowerPoint puts templates).
        tiles = QHBoxLayout()
        tiles.setSpacing(16)
        self.tile_load = _tile(
            "Load packet data", "Open an AMPM packet and explore it in the grid."
        )
        self.tile_excel = _tile(
            "Create Excel from AMPM",
            "Generate samples-template workbooks from a build directory.",
        )
        self.tile_load.clicked.connect(self.loadRequested)
        self.tile_excel.clicked.connect(self.createExcelRequested)
        tiles.addWidget(self.tile_load)
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

        return main

    def _divider(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        return line
