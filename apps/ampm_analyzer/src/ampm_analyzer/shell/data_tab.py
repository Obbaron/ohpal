"""Data tab — the grid view / data-shaping staging area.

A virtualised table (QTableView + DataFrameModel) over the current query
result: it shows the full layer without a row cap, pulling only the visible
cells. Columnar selection is the unit all data actions operate on.

The data *toolbar* lives on the main window (it swaps per active tab); this
widget is only the grid surface.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from .grid_model import DataFrameModel


class DataTab(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("tabkind", "data")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        self.model = DataFrameModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.verticalHeader().setVisible(False)

        # Columnar selection only — click a header to select the whole column.
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectColumns
        )
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        lay.addWidget(self.table)

    @property
    def _columns(self) -> list[str]:
        return self.model.columns

    def selected_columns(self) -> list[str]:
        """Headers of the currently selected columns (used later by New plot)."""
        sel = self.table.selectionModel()
        if sel is None:
            return []
        cols = sorted(idx.column() for idx in sel.selectedColumns())
        names = self.model.columns
        return [names[c] for c in cols if c < len(names)]

    def set_dataframe(self, df) -> None:
        """Show a Polars DataFrame (full layer; the model virtualises rows)."""
        self.model.set_dataframe(df)
