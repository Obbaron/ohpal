"""Data tab — the grid view / data-shaping staging area.

A virtualised table (QTableView + DataFrameModel) over the current query
result. Columns can be reordered by dragging headers and shown/hidden from the
toolbar dropdown; the layout (order / hidden / widths) is captured as a header
blob and persisted per build by the window.

The data *toolbar* lives on the main window (it swaps per active tab); this
widget is only the grid surface.
"""

from __future__ import annotations

from PyQt6.QtCore import QByteArray, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from .grid_model import DataFrameModel


class ReorderHeader(QHeaderView):
    """Movable header that draws a drop-position indicator while dragging.

    QHeaderView already shows a translucent ghost of the dragged section; this
    adds a clear accent line at the boundary where it will land on release.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setSectionsMovable(True)
        self.setSectionsClickable(True)
        self._drop_x: int | None = None

    def mouseMoveEvent(self, event) -> None:
        super().mouseMoveEvent(event)  # let Qt do the ghost drag
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        x = int(event.position().x())
        vi = self.visualIndexAt(x)
        if vi == -1:
            return
        logical = self.logicalIndex(vi)
        left = self.sectionViewportPosition(logical)
        width = self.sectionSize(logical)
        drop = left + width if x > left + width / 2 else left
        if drop == self._drop_x:
            return  # line hasn't moved — skip the repaint
        old = self._drop_x
        self._drop_x = drop
        vp = self.viewport()
        if old is not None:  # clear the old line's strip
            vp.update(old - 2, 0, 5, self.height())
        vp.update(drop - 2, 0, 5, self.height())  # draw the new one

    def mouseReleaseEvent(self, event) -> None:
        self._drop_x = None
        self.viewport().update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._drop_x is None:
            return
        painter = QPainter(self.viewport())
        pen = QPen(self.palette().color(self.palette().ColorRole.Highlight))
        pen.setWidth(3)
        painter.setPen(pen)
        painter.drawLine(self._drop_x, 0, self._drop_x, self.height())
        painter.end()

# Default visual order (left → right) and the columns hidden by default.
DEFAULT_ORDER = [
    "Start time", "Duration", "Demand focus", "layer",
    "Demand X", "Demand Y", "Z",
    "Demand laser power (mean)", "Laser output power (mean)",
    "MeltVIEW melt pool (mean)", "MeltVIEW plasma (mean)",
    "LaserVIEW (mean)", "Laser back reflection (mean)",
    "Demand laser power (median)", "Laser output power (median)",
    "MeltVIEW melt pool (median)", "MeltVIEW plasma (median)",
    "LaserVIEW (median)", "Laser back reflection (median)",
]
DEFAULT_HIDDEN = {"Start time", "Duration", "Demand focus", "layer"}


class DataTab(QWidget):
    # Emitted when the user changes the column layout (reorder / show-hide /
    # resize) — the window persists it per build.
    layoutChanged = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("tabkind", "data")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._filter_bar = self._build_filter_bar()
        lay.addWidget(self._filter_bar)

        self.model = DataFrameModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.verticalHeader().setVisible(False)

        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectColumns
        )
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        header = ReorderHeader(self.table)  # movable + drop-position indicator
        self.table.setHorizontalHeader(header)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.sectionMoved.connect(self._on_header_changed)
        header.sectionResized.connect(lambda *_: self._on_header_changed())

        lay.addWidget(self.table)

        self._applying = False      # suppress layoutChanged during programmatic apply
        self._persisted: bytes | None = None  # saved header blob for this build
        self._layout_done = False   # whether the layout has been applied once
        self._last_state: bytes | None = None  # most recent captured header blob
        # Name-based layout snapshot, used when the column set changes (add /
        # remove) — restoring a count-mismatched blob corrupts the header.
        self._last_cols: list[str] = []
        self._order_names: list[str] = []
        self._hidden_names: set[str] = set()

    # -- filter chip bar -----------------------------------------------
    def _build_filter_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("FilterBar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(8, 4, 10, 4)
        h.setSpacing(6)
        h.addWidget(QLabel("Filter:"))
        self._chips = QHBoxLayout()
        self._chips.setSpacing(6)
        h.addLayout(self._chips)
        h.addStretch(1)
        self._count = QLabel("")
        self._count.setProperty("class", "PanelHeading")
        h.addWidget(self._count)
        bar.setVisible(False)
        return bar

    def set_filters(self, conditions, shown, total, on_remove) -> None:
        """Show active filter chips (✕ to remove) and the shown/total count."""
        while self._chips.count():
            item = self._chips.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for i, cond in enumerate(conditions):
            label = cond if len(cond) <= 40 else cond[:37] + "…"
            chip = QPushButton(f"{label}  ✕")
            chip.setToolTip(cond)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(lambda _c=False, idx=i: on_remove(idx))
            self._chips.addWidget(chip)
        if conditions:
            self._count.setText(f"{shown:,} of {total:,} rows")
        self._filter_bar.setVisible(bool(conditions))

    # -- model ---------------------------------------------------------
    @property
    def _columns(self) -> list[str]:
        return self.model.columns

    def selected_columns(self) -> list[str]:
        sel = self.table.selectionModel()
        if sel is None:
            return []
        cols = sorted(idx.column() for idx in sel.selectedColumns())
        names = self.model.columns
        return [names[c] for c in cols if c < len(names)]

    def set_dataframe(self, df) -> None:
        """Show a Polars DataFrame; (re)apply the column layout."""
        first = not self._layout_done
        new_cols = list(df.columns)
        cols_changed = (not first) and (new_cols != self._last_cols)
        self.model.set_dataframe(df)
        self._apply_layout(first, cols_changed)
        self._last_cols = new_cols
        # A column added mid-session (e.g. a new derived column, often off-screen
        # to the right) can leave the view's geometry stale and paint blank until
        # a reload. Force a re-layout + repaint so it shows immediately.
        self.table.doItemsLayout()
        self.table.viewport().update()

    # -- layout / persistence ------------------------------------------
    def set_persisted_state(self, state: bytes | None) -> None:
        """Hand the window's saved header blob (or None for defaults)."""
        self._persisted = state
        self._layout_done = False

    def _apply_layout(self, first: bool, cols_changed: bool = False) -> None:
        self._applying = True
        try:
            header = self.table.horizontalHeader()
            if first:
                # Build load: restore the saved per-build blob, else defaults.
                if self._persisted is not None:
                    header.restoreState(QByteArray(self._persisted))
                else:
                    self._apply_defaults()
            elif cols_changed:
                # Column added/removed: re-apply the user's order + hidden set
                # BY NAME (new columns append, visible). Restoring the old blob
                # here would corrupt the header — its section count is stale.
                self._apply_named_layout()
            elif self._last_state is not None:
                # Same columns (e.g. a layer change): re-assert the exact layout
                # (order / hidden / widths) so a model reset can't drop it.
                header.restoreState(QByteArray(self._last_state))
        finally:
            self._applying = False
            self._capture_names()
            self._last_state = bytes(header.saveState())
            self._layout_done = True

    def _capture_names(self) -> None:
        """Snapshot the current visual order + hidden set, by column name."""
        header = self.table.horizontalHeader()
        cols = self.model.columns
        n = len(cols)
        self._order_names = [
            cols[header.logicalIndex(v)] for v in range(n)
            if 0 <= header.logicalIndex(v) < n
        ]
        self._hidden_names = {
            cols[i] for i in range(n) if header.isSectionHidden(i)
        }

    def _apply_named_layout(self) -> None:
        """Reorder + hide by saved column names; new columns go last, visible."""
        header = self.table.horizontalHeader()
        cols = self.model.columns
        logical = {name: i for i, name in enumerate(cols)}
        desired = [n for n in self._order_names if n in logical]
        desired += [n for n in cols if n not in self._order_names]
        for target_vis, name in enumerate(desired):
            cur_vis = header.visualIndex(logical[name])
            if cur_vis != target_vis:
                header.moveSection(cur_vis, target_vis)
        for name, i in logical.items():
            header.setSectionHidden(i, name in self._hidden_names)

    def _apply_defaults(self) -> None:
        header = self.table.horizontalHeader()
        cols = self.model.columns
        logical = {name: i for i, name in enumerate(cols)}
        desired = [n for n in DEFAULT_ORDER if n in logical]
        desired += [n for n in cols if n not in DEFAULT_ORDER]
        for target_vis, name in enumerate(desired):
            cur_vis = header.visualIndex(logical[name])
            if cur_vis != target_vis:
                header.moveSection(cur_vis, target_vis)
        for name in DEFAULT_HIDDEN:
            if name in logical:
                header.setSectionHidden(logical[name], True)

    def _on_header_changed(self, *args) -> None:
        if self._applying:
            return
        self._capture_names()  # keep the name snapshot current for column changes
        self._last_state = bytes(self.table.horizontalHeader().saveState())
        self.layoutChanged.emit()

    def current_state(self) -> bytes:
        return bytes(self.table.horizontalHeader().saveState())

    # -- show / hide ---------------------------------------------------
    def hidden_columns(self) -> set[str]:
        header = self.table.horizontalHeader()
        cols = self.model.columns
        return {
            name for i, name in enumerate(cols) if header.isSectionHidden(i)
        }

    def set_column_visible(self, name: str, visible: bool) -> None:
        cols = self.model.columns
        if name not in cols:
            return
        self.table.horizontalHeader().setSectionHidden(cols.index(name), not visible)
        self._on_header_changed()
