"""Data tab — the grid view / data-shaping staging area.

A table with columnar selection (the unit all data actions operate on). Filled
with placeholder rows so the layout reads; the real model is wired later.

The data *toolbar* lives on the main window (it swaps per active tab); this
widget is only the grid surface.
"""

from __future__ import annotations

import random

from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

# 15 domain-plausible columns, matching the design doc's "15 columns".
COLUMNS = [
    "part_id", "instance", "X", "Y", "Z", "layer", "speed", "power",
    "focus", "hatch", "area", "volume", "build", "source", "tag",
]

_SAMPLE_ROWS = 30


def _sample_value(col: str, row: int) -> str:
    if col == "part_id":
        return f"Part({(row % 12) + 1})"
    if col == "instance":
        return str(row + 1)
    if col in ("X", "Y", "Z"):
        return f"{random.uniform(0, 250):.2f}"
    if col == "layer":
        return str(random.randint(1, 80))
    if col in ("speed", "power", "focus", "hatch"):
        return f"{random.uniform(50, 400):.1f}"
    if col in ("area", "volume"):
        return f"{random.uniform(1, 999):.2f}"
    if col == "build":
        return random.choice(["JR299", "JR295", "JR324"])
    if col == "source":
        return random.choice(["dhxml+CSV", "CSV"])
    if col == "tag":
        return ""
    return ""


class DataTab(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("tabkind", "data")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget(_SAMPLE_ROWS, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
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

        for r in range(_SAMPLE_ROWS):
            for c, col in enumerate(COLUMNS):
                self.table.setItem(r, c, QTableWidgetItem(_sample_value(col, r)))

        lay.addWidget(self.table)
        self._columns: list[str] = list(COLUMNS)

    def selected_columns(self) -> list[str]:
        """Headers of the currently selected columns (used later by New plot)."""
        cols = sorted({idx.column() for idx in self.table.selectedIndexes()})
        return [self._columns[c] for c in cols if c < len(self._columns)]

    def set_dataframe(self, df) -> None:
        """Populate the grid from a Polars DataFrame (Stage 1: capped sample).

        This is a simple QTableWidget fill; the virtualised model arrives in
        Stage 3. ``df`` is expected to be already row-capped by the caller.
        """
        cols = list(df.columns)
        self._columns = cols
        self.table.clear()
        self.table.setColumnCount(len(cols))
        self.table.setRowCount(df.height)
        self.table.setHorizontalHeaderLabels(cols)

        # Iterate columns (Polars is columnar) and format cells.
        for c, name in enumerate(cols):
            series = df[name]
            is_float = series.dtype.is_float()
            for r, value in enumerate(series.to_list()):
                if value is None:
                    text = ""
                elif is_float:
                    text = f"{value:.4g}"
                else:
                    text = str(value)
                self.table.setItem(r, c, QTableWidgetItem(text))
