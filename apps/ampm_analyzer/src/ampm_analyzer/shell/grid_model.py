"""Virtualised grid model over a Polars DataFrame.

A ``QAbstractTableModel`` that serves cells on demand, so a QTableView only
pulls the rows it actually paints (~a screenful). This shows a full layer
(100k+ rows) without copying every cell — no row cap needed. Floats render at
4 significant figures; nulls render blank.
"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt


class DataFrameModel(QAbstractTableModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._df = None
        self._columns: list[str] = []
        self._series: list[Any] = []  # per-column Polars Series (fast access)
        self._is_float: list[bool] = []

    def set_dataframe(self, df) -> None:
        self.beginResetModel()
        self._df = df
        self._columns = list(df.columns)
        self._series = [df[c] for c in self._columns]
        self._is_float = [s.dtype.is_float() for s in self._series]
        self.endResetModel()

    @property
    def columns(self) -> list[str]:
        return list(self._columns)

    # -- Qt model API --------------------------------------------------
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid() or self._df is None:
            return 0
        return self._df.height

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._columns)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        r, c = index.row(), index.column()
        value = self._series[c][r]
        if value is None:
            return ""
        if self._is_float[c]:
            return f"{value:.4g}"
        return str(value)

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self._columns[section] if section < len(self._columns) else None
        return section + 1  # 1-based row numbers
