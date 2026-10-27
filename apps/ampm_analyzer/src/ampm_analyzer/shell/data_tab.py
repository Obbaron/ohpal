"""Data tab — the grid view / data-shaping staging area.

A virtualised table (QTableView + DataFrameModel) over the current query
result. Columns can be reordered by dragging headers and shown/hidden from the
toolbar dropdown; the layout (order / hidden / widths) is captured as a header
blob and persisted per build by the window.

The data *toolbar* lives on the main window (it swaps per active tab); this
widget is only the grid surface.
"""

from __future__ import annotations

from PyQt6.QtCore import QByteArray, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from .grid_model import DataFrameModel


class ReorderHeader(QHeaderView):
    """Header with our own lightweight column reordering.

    Qt's built-in movable sections composite a translucent ghost of the dragged
    column on every mouse move, which is the drag lag. Here sections are *not*
    Qt-movable; we handle the drag ourselves, drawing only a thin drop-position
    line and highlighting the grabbed header — far cheaper. Auto-scroll near the
    edges is our own, throttled on a timer, so a column can still be dragged to
    an off-screen position without the repaint storm.

    A click without a drag falls through to the base class, preserving
    click-to-select-column.
    """

    _DRAG_THRESHOLD = 6   # px of movement before a click becomes a drag
    _EDGE_MARGIN = 28     # px from an edge that starts auto-scroll
    _SCROLL_STEP = 28     # px per throttled scroll tick
    _SCROLL_MS = 40       # auto-scroll tick interval

    def __init__(self, parent=None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setSectionsMovable(False)   # we handle reordering -> no Qt ghost
        self.setSectionsClickable(True)
        self._view = parent              # the QTableView
        self._drop_x: int | None = None
        self._grab_logical = -1
        self._press_x: float | None = None
        self._dragging = False
        self._last_x = 0
        self._scroll_dir = 0
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setInterval(self._SCROLL_MS)
        self._scroll_timer.timeout.connect(self._auto_scroll_step)

    # -- mouse ---------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_x = event.position().x()
            self._grab_logical = self.logicalIndexAt(int(self._press_x))
            self._dragging = False
        super().mousePressEvent(event)  # allow click-to-select to start

    def mouseMoveEvent(self, event) -> None:
        if not (event.buttons() & Qt.MouseButton.LeftButton) or self._grab_logical < 0:
            super().mouseMoveEvent(event)
            return
        x = int(event.position().x())
        self._last_x = x
        if not self._dragging:
            if self._press_x is None or abs(x - self._press_x) < self._DRAG_THRESHOLD:
                super().mouseMoveEvent(event)
                return
            self._dragging = True  # begin reorder; stop feeding super (no select-drag)
        self._update_drop(x)
        self._update_edge_scroll(x)

    def mouseReleaseEvent(self, event) -> None:
        self._scroll_timer.stop()
        self._scroll_dir = 0
        if self._dragging:
            self._perform_move(int(event.position().x()))
            self._dragging = False
            self._drop_x = None
            self._grab_logical = -1
            self.viewport().update()
            return  # swallow: a drag is not a click/selection
        self._grab_logical = -1
        super().mouseReleaseEvent(event)  # plain click -> select column

    # -- drop indicator + reorder --------------------------------------
    def _drop_x_for(self, x: int) -> int:
        vi = self.visualIndexAt(x)
        if vi == -1:
            return self.viewport().width()  # past the last column -> far right
        logical = self.logicalIndex(vi)
        left = self.sectionViewportPosition(logical)
        width = self.sectionSize(logical)
        return left + width if x > left + width / 2 else left

    def _update_drop(self, x: int) -> None:
        drop = self._drop_x_for(x)
        if drop == self._drop_x:
            return
        old = self._drop_x
        self._drop_x = drop
        vp = self.viewport()
        if old is not None:
            vp.update(old - 2, 0, 5, self.height())
        vp.update(drop - 2, 0, 5, self.height())

    def _perform_move(self, x: int) -> None:
        if self._grab_logical < 0:
            return
        from_vis = self.visualIndex(self._grab_logical)
        vi = self.visualIndexAt(x)
        if vi == -1:
            to_vis = self.count() - 1
        else:
            logical = self.logicalIndex(vi)
            left = self.sectionViewportPosition(logical)
            width = self.sectionSize(logical)
            to_vis = vi + 1 if x > left + width / 2 else vi
            if to_vis > from_vis:
                to_vis -= 1  # removal shifts targets left of the insertion point
        to_vis = max(0, min(self.count() - 1, to_vis))
        if to_vis != from_vis:
            self.moveSection(from_vis, to_vis)

    # -- throttled auto-scroll -----------------------------------------
    def _update_edge_scroll(self, x: int) -> None:
        w = self.viewport().width()
        if x > w - self._EDGE_MARGIN:
            self._scroll_dir = 1
        elif x < self._EDGE_MARGIN:
            self._scroll_dir = -1
        else:
            self._scroll_dir = 0
        if self._scroll_dir and not self._scroll_timer.isActive():
            self._scroll_timer.start()
        elif not self._scroll_dir and self._scroll_timer.isActive():
            self._scroll_timer.stop()

    def _auto_scroll_step(self) -> None:
        if self._view is None or not self._scroll_dir:
            return
        sb = self._view.horizontalScrollBar()
        new = sb.value() + self._scroll_dir * self._SCROLL_STEP
        sb.setValue(max(sb.minimum(), min(sb.maximum(), new)))
        self.viewport().update()  # sections moved under the cursor
        self._update_drop(self._last_x)

    # -- paint ---------------------------------------------------------
    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self.viewport())
        # Highlight the grabbed column's header while dragging (light "ghost").
        if self._dragging and self._grab_logical >= 0:
            left = self.sectionViewportPosition(self._grab_logical)
            width = self.sectionSize(self._grab_logical)
            fill = QColor(self.palette().color(self.palette().ColorRole.Highlight))
            fill.setAlpha(40)
            painter.fillRect(left, 0, width, self.height(), fill)
        if self._drop_x is not None:
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
        self.model.set_dataframe(df)
        self._apply_layout(first)

    # -- layout / persistence ------------------------------------------
    def set_persisted_state(self, state: bytes | None) -> None:
        """Hand the window's saved header blob (or None for defaults)."""
        self._persisted = state
        self._layout_done = False

    def _apply_layout(self, first: bool) -> None:
        # On the first population, restore the saved blob or apply defaults.
        # Later populations (layer changes) re-assert the same layout so a model
        # reset can't drop it.
        self._applying = True
        try:
            header = self.table.horizontalHeader()
            if self._persisted is not None:
                header.restoreState(QByteArray(self._persisted))
            elif first:
                self._apply_defaults()
            else:
                # no saved state, but keep the current (user/default) order by
                # re-applying what we have captured so far
                if self._last_state is not None:
                    header.restoreState(QByteArray(self._last_state))
        finally:
            self._applying = False
            self._last_state = bytes(header.saveState())
            self._layout_done = True

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
