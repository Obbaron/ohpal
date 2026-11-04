"""Data tab — the grid view / data-shaping staging area.

A virtualised table (QTableView + DataFrameModel) over the current query
result. Columns can be reordered by dragging headers and shown/hidden from the
toolbar dropdown; the layout (order / hidden / widths) is captured as a header
blob and persisted per build by the window.

The data *toolbar* lives on the main window (it swaps per active tab); this
widget is only the grid surface.
"""

from __future__ import annotations

from PyQt6.QtCore import QByteArray, QEvent, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableView,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .grid_model import DataFrameModel


class _HeaderRenameEdit(QLineEdit):
    """A transient editor floated over a header section to rename a column.

    Enter commits, Esc or clicking away cancels — all funnelled through one
    ``done(bool)`` signal (True = commit)."""

    done = pyqtSignal(bool)

    def keyPressEvent(self, e) -> None:  # noqa: N802 (Qt override)
        if e.key() == Qt.Key.Key_Escape:
            self.done.emit(False)
            return
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.done.emit(True)
            return
        super().keyPressEvent(e)

    def focusOutEvent(self, e) -> None:  # noqa: N802
        super().focusOutEvent(e)
        self.done.emit(False)  # click away cancels


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
    # Emitted when a column header is renamed inline (old name, new name).
    renameRequested = pyqtSignal(str, str)

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
        header.sectionClicked.connect(self._on_section_clicked)
        header.sectionDoubleClicked.connect(self._begin_rename)

        # Clicking empty grid space clears the column selection.
        self.table.viewport().installEventFilter(self)

        # Inline column-rename state.
        self._rename_armed = False
        self._editor: _HeaderRenameEdit | None = None
        self._editing_old = ""

        lay.addWidget(self.table)

        self._applying = False      # suppress layoutChanged during programmatic apply
        self._persisted: bytes | None = None  # saved header blob for this build
        self._persisted_cols: list[str] = []  # columns the blob was saved with
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

    def set_filters(self, conditions, shown, total, on_remove, on_edit) -> None:
        """Show active filter chips and the shown/total count.

        Clicking a chip's label edits that condition; the ✕ removes it.
        """
        while self._chips.count():
            item = self._chips.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for i, cond in enumerate(conditions):
            self._chips.addWidget(self._make_chip(i, cond, on_remove, on_edit))
        if conditions:
            self._count.setText(f"{shown:,} of {total:,} rows")
        self._filter_bar.setVisible(bool(conditions))

    def _make_chip(self, index, cond, on_remove, on_edit) -> QFrame:
        chip = QFrame()
        chip.setProperty("class", "FilterChip")
        h = QHBoxLayout(chip)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        one_line = " ".join(cond.split())
        label = one_line if len(one_line) <= 40 else one_line[:37] + "…"
        edit = QPushButton(label)
        edit.setToolTip(f"{cond}\n\nClick to edit")
        edit.setCursor(Qt.CursorShape.PointingHandCursor)
        edit.clicked.connect(lambda _c=False, idx=index: on_edit(idx))
        close = QToolButton()
        close.setText("✕")
        close.setToolTip("Remove this condition")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(lambda _c=False, idx=index: on_remove(idx))
        h.addWidget(edit)
        h.addWidget(close)
        return chip

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

    # -- inline column rename ------------------------------------------
    def start_rename(self) -> None:
        """Toolbar entry: rename the selected column now; with no selection, arm
        click-to-rename (the next header click opens the editor)."""
        cols = self.selected_columns()
        if cols:
            try:
                self._begin_rename(self.model.columns.index(cols[0]))
                return
            except ValueError:
                pass
        self._arm_rename()

    def _arm_rename(self) -> None:
        if self._rename_armed:
            return
        self._rename_armed = True
        # Whole-window I-beam (not just the header), and watch for the click
        # that lands somewhere other than a header — that cancels rename mode.
        QApplication.setOverrideCursor(Qt.CursorShape.IBeamCursor)
        QApplication.instance().installEventFilter(self)

    def _disarm_rename(self) -> None:
        if not self._rename_armed:
            return
        self._rename_armed = False
        QApplication.restoreOverrideCursor()
        QApplication.instance().removeEventFilter(self)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt override)
        if event.type() == QEvent.Type.MouseButtonPress:
            # Deselect: a press on empty grid space clears the selection.
            if obj is self.table.viewport():
                pos = event.position().toPoint()
                if not self.table.indexAt(pos).isValid():
                    self.table.clearSelection()
            # Armed: anything but a header press cancels rename mode (the header
            # press is handled by sectionClicked, which renames).
            if self._rename_armed:
                header = self.table.horizontalHeader()
                if obj is not header.viewport() and obj is not header:
                    self._disarm_rename()
        return False  # never consume — just observe

    def _on_section_clicked(self, logical: int) -> None:
        if self._rename_armed:
            self._disarm_rename()
            self._begin_rename(logical)

    def _begin_rename(self, logical: int) -> None:
        self._disarm_rename()
        cols = self.model.columns
        if not (0 <= logical < len(cols)):
            return
        if self._editor is not None:
            self._finish_rename(False)
        header = self.table.horizontalHeader()
        self._editing_old = cols[logical]
        ed = _HeaderRenameEdit(header)
        ed.setText(self._editing_old)
        ed.selectAll()
        ed.setGeometry(
            header.sectionViewportPosition(logical), 0,
            header.sectionSize(logical), header.height())
        ed.done.connect(self._finish_rename)
        self._editor = ed
        ed.show()
        ed.setFocus()

    def _finish_rename(self, commit: bool) -> None:
        ed = self._editor
        if ed is None:
            return
        self._editor = None  # guard re-entry (hide() can fire focusOut)
        new = ed.text().strip()
        old = self._editing_old
        ed.hide()
        ed.deleteLater()
        if commit and new and new != old:
            self.renameRequested.emit(old, new)

    def rename_in_layout(self, old: str, new: str) -> None:
        """Swap a column name in the name-based layout snapshots. Call this just
        *before* the grid refresh that carries the renamed column: with
        ``_last_cols`` already holding the new name, the refresh sees an
        unchanged column set and restores the exact header state (order / hidden
        / widths) by index — so only the label changes, nothing moves."""
        self._order_names = [new if c == old else c for c in self._order_names]
        self._hidden_names = {new if c == old else c for c in self._hidden_names}
        self._last_cols = [new if c == old else c for c in self._last_cols]

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
    def set_persisted_state(self, state: bytes | None, columns=None,
                            order=None, hidden=None) -> None:
        """Hand the window's saved header blob + the columns it was saved with.

        ``order``/``hidden`` (column names) let the grid lay out by name when
        the blob's column set no longer matches (a stale blob would corrupt the
        header mapping).
        """
        self._persisted = state
        self._persisted_cols = list(columns or [])
        self._order_names = list(order or [])
        self._hidden_names = set(hidden or [])
        self._layout_done = False

    def _apply_layout(self, first: bool, cols_changed: bool = False) -> None:
        self._applying = True
        try:
            header = self.table.horizontalHeader()
            if first:
                # Build load: restore the saved blob ONLY when its columns match
                # the current ones exactly (same logical set + order) — otherwise
                # the blob's section mapping is stale and would scramble the
                # header. On a mismatch, lay out by saved name, else defaults.
                if (self._persisted is not None
                        and self._persisted_cols == list(self.model.columns)):
                    header.restoreState(QByteArray(self._persisted))
                elif self._order_names or self._hidden_names:
                    self._apply_named_layout()
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

    def place_after(self, name: str, after: str) -> None:
        """Move column ``name`` to directly follow ``after`` in the visual order,
        and persist it (via the name snapshot). No-op if either is missing."""
        header = self.table.horizontalHeader()
        cols = list(self.model.columns)
        if name not in cols or after not in cols or name == after:
            return
        order = [c for c in self._order_names if c in cols]
        order += [c for c in cols if c not in order]  # fold in any un-snapshotted
        if name in order:
            order.remove(name)
        idx = order.index(after) + 1 if after in order else len(order)
        order.insert(idx, name)
        logical = {n: i for i, n in enumerate(cols)}
        self._applying = True
        try:
            for target_vis, n in enumerate(order):
                cur_vis = header.visualIndex(logical[n])
                if cur_vis != target_vis:
                    header.moveSection(cur_vis, target_vis)
        finally:
            self._applying = False
            self._capture_names()
            self._last_state = bytes(header.saveState())
        self.layoutChanged.emit()

    def current_state(self) -> bytes:
        return bytes(self.table.horizontalHeader().saveState())

    def layout_names(self) -> tuple[list, list, list]:
        """Logical columns, visual order (names), hidden (names) — for persistence."""
        return (list(self.model.columns), list(self._order_names),
                sorted(self._hidden_names))

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
