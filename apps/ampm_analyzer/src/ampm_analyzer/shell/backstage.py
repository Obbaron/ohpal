"""File tab — the backstage, modelled on PowerPoint's File view.

Full-window takeover (no per-tab toolbar). Left sidebar of file actions; a main
area that stacks a Start page (primary tiles + Recent/Favourites/Search), a
DataStore page and the Plot library (frozen plots, openable with or without a
build). The DataStore entry appears dynamically once a build is loaded
— the backstage is where the parquet-cache definition (columns, ranges, bounds,
pipeline) is created and rebuilt.

Inert except for *structural* navigation signals the main window uses:
``loadRequested``, ``createExcelRequested``, and ``datastoreCreateRequested``.
"""

from __future__ import annotations

from datetime import datetime, timezone

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import icons, plot_library
from .datastore_settings import DataStoreSettings
from .recents import RecentStore


def _humanize(iso: str) -> str:
    """Compact relative time: 'just now', '2h ago', '3d ago', else a date."""
    try:
        then = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return ""
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    secs = (datetime.now(timezone.utc) - then).total_seconds()
    if secs < 90:
        return "just now"
    if secs < 90 * 60:
        return f"{round(secs / 60)}m ago"
    if secs < 36 * 3600:
        return f"{round(secs / 3600)}h ago"
    if secs < 14 * 86400:
        return f"{round(secs / 86400)}d ago"
    if secs < 9 * 7 * 86400:
        return f"{round(secs / (7 * 86400))}w ago"
    return then.strftime("%Y-%m-%d")



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
    openRecentRequested = pyqtSignal(str)   # open a build chosen from Recent
    libraryOpenRequested = pyqtSignal(str)  # open a frozen plot (its file)
    libraryBrowseRequested = pyqtSignal()   # open one from anywhere
    libraryFolderRequested = pyqtSignal()   # show the library folder

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Backstage")
        self.setProperty("tabkind", "file")

        self._recents = RecentStore()
        self._recent_filter = "recent"  # "recent" | "favourites" | "shared"

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_sidebar())
        root.addWidget(self._build_main(), 1)

        self.refresh_recents()

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
        self.btn_library = add("Plot library", primary=True)
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
        self.btn_library.clicked.connect(self.show_library_page)
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
        self.main_stack.addWidget(self._library_page())     # index 2
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
        for i, (name, key) in enumerate(
            (("Recent", "recent"), ("Favourites", "favourites"),
             ("Shared with Me", "shared"))
        ):
            b = QPushButton(name)
            b.setCheckable(True)
            if i == 0:
                b.setChecked(True)
            b.clicked.connect(lambda _c, k=key: self._set_recent_filter(k))
            self.grp.addButton(b)
            strip.addWidget(b)
        strip.addStretch(1)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search for a file")
        self.search.setFixedWidth(280)
        self.search.textChanged.connect(lambda _t: self.refresh_recents())
        strip.addWidget(self.search)
        lay.addLayout(strip)

        self.recent = QListWidget()
        self.recent.itemDoubleClicked.connect(self._on_recent_activated)
        lay.addWidget(self.recent, 1)
        return page

    # -- recents -------------------------------------------------------
    def _set_recent_filter(self, key: str) -> None:
        self._recent_filter = key
        self.refresh_recents()

    def refresh_recents(self) -> None:
        """Repopulate the Recent list from the store (pruning missing folders)."""
        if not hasattr(self, "recent"):
            return
        self.recent.clear()
        query = self.search.text().strip().lower() if hasattr(self, "search") else ""
        for e in self._recents.load():  # newest-first, already pruned
            if self._recent_filter == "favourites" and not e.favourite:
                continue
            if self._recent_filter == "shared":
                continue  # not wired yet
            if query and query not in e.name.lower():
                continue
            self._add_recent_row(e)

    def _add_recent_row(self, entry) -> None:
        item = QListWidgetItem(self.recent)
        item.setData(Qt.ItemDataRole.UserRole, entry.path)

        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(10, 4, 8, 4)
        h.setSpacing(8)
        status = "ready" if entry.has_cache else "needs build"
        label = QLabel(f"{entry.name}  ·  {status}  ·  {_humanize(entry.last_opened)}")
        label.setToolTip(entry.path)
        h.addWidget(label, 1)

        star = QToolButton()
        star.setCheckable(True)
        star.setChecked(entry.favourite)
        star.setText("★" if entry.favourite else "☆")
        star.setToolTip("Remove from Favourites" if entry.favourite
                        else "Add to Favourites")
        star.setAutoRaise(True)
        star.setCursor(Qt.CursorShape.PointingHandCursor)
        star.clicked.connect(
            lambda checked, p=entry.path: self._on_star_toggled(p, checked)
        )
        h.addWidget(star, 0)

        item.setSizeHint(row.sizeHint())
        self.recent.setItemWidget(item, row)

    def _on_recent_activated(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.openRecentRequested.emit(path)

    def _on_star_toggled(self, path: str, favourite: bool) -> None:
        self._recents.set_favourite(path, favourite)
        self.refresh_recents()

    def _datastore_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(32, 28, 32, 28)
        lay.setSpacing(10)

        heading = QLabel("DataStore")
        heading.setProperty("class", "SectionHeading")
        lay.addWidget(heading)
        sub = QLabel(
            "Load this build into a dataset you can sort, shape, and plot. "
            "Set the layer range, thickness, and columns, then build."
        )
        sub.setProperty("class", "TileSub")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.ds_form = DataStoreSettings()
        self.ds_form.buildRequested.connect(self.datastoreBuildRequested)
        self.ds_form.cancelRequested.connect(self.show_start_page)
        scroll.setWidget(self.ds_form)
        lay.addWidget(scroll, 1)
        return page

    # -- plot library ----------------------------------------------------
    def _library_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(32, 28, 32, 28)
        lay.setSpacing(10)
        heading = QLabel("Plot library")
        heading.setProperty("class", "SectionHeading")
        lay.addWidget(heading)
        sub = QLabel(
            "Frozen plots: each keeps the data of the build it was saved from, "
            "so plots of different builds can be opened side by side. Save one "
            "from a plot's toolbar.")
        sub.setProperty("class", "TileSub")
        sub.setWordWrap(True)
        lay.addWidget(sub)

        strip = QHBoxLayout()
        strip.setSpacing(8)
        self.lib_search = QLineEdit()
        self.lib_search.setPlaceholderText("Search by title, build or kind")
        self.lib_search.setFixedWidth(280)
        self.lib_search.textChanged.connect(lambda _t: self.refresh_library())
        strip.addWidget(self.lib_search)
        strip.addStretch(1)
        self.lib_open = QPushButton("Open")
        self.lib_open.setProperty("primary", "true")
        self.lib_open.clicked.connect(self._open_selected_plot)
        strip.addWidget(self.lib_open)
        browse = QPushButton("Browse…")
        browse.setToolTip("Open a saved plot from another folder")
        browse.clicked.connect(self.libraryBrowseRequested)
        strip.addWidget(browse)
        folder = QPushButton("Open folder")
        folder.clicked.connect(self.libraryFolderRequested)
        strip.addWidget(folder)
        lay.addLayout(strip)

        self.library = QListWidget()
        self.library.setSpacing(3)
        self.library.itemDoubleClicked.connect(
            lambda item: self._emit_open(item))
        self.library.currentItemChanged.connect(
            lambda *_: self.lib_open.setEnabled(
                self.library.currentItem() is not None))
        lay.addWidget(self.library, 1)
        self.lib_empty = QLabel("")
        self.lib_empty.setProperty("class", "TileSub")
        self.lib_empty.setWordWrap(True)
        lay.addWidget(self.lib_empty)
        return page

    def refresh_library(self) -> None:
        """List the library folder's plots (newest first, searched)."""
        if not hasattr(self, "library"):
            return
        self.library.clear()
        query = self.lib_search.text().strip().lower()
        shown = 0
        for e in plot_library.entries():
            text = f"{e.title}\n{e.kind}  ·  from {e.build}  ·  {e.saved_text}" \
                   f"  ·  {e.rows:,} rows"
            if query and query not in f"{e.title} {e.build} {e.kind}".lower():
                continue
            item = QListWidgetItem(text, self.library)
            item.setData(Qt.ItemDataRole.UserRole, e.path)
            item.setToolTip(e.path)
            item.setIcon(icons.for_view(e.kind, self.palette().text().color().name()))
            shown += 1
        self.lib_open.setEnabled(False)
        if shown:
            self.lib_empty.setText("")
        elif query:
            self.lib_empty.setText("No saved plots match.")
        else:
            self.lib_empty.setText(
                f"No plots saved yet. The library is {plot_library.folder()}.")

    def _emit_open(self, item) -> None:
        path = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if path:
            self.libraryOpenRequested.emit(path)

    def _open_selected_plot(self) -> None:
        self._emit_open(self.library.currentItem())

    def show_library_page(self) -> None:
        self.refresh_library()
        self.main_stack.setCurrentIndex(2)

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
        self,
        config: dict,
        layers: list[int],
        columns: list[str] | None = None,
        renames: dict | None = None,
        included: list[str] | None = None,
    ) -> None:
        self.ds_form.set_config(config, layers, columns, renames, included)

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
            self.btn_library: "plot_library",
            self.btn_datastore: "datastore",
            self.btn_export: "export",
            self.btn_info: "info",
            self.btn_close: "close",
        }
        for button, name in mapping.items():
            button.setIcon(icons.ui(name, color))
