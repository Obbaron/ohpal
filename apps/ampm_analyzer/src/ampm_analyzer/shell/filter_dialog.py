"""Dialog for adding a row filter condition.

A condition is a boolean predicate in the same DSL as derived columns, e.g.
``[Demand X] >= -32 and [Demand X] <= -28``. Columns insert in ``[brackets]``.
A "Spatial box" helper fills the common X/Y-bounds case. Validated on OK against
the available columns (including derived ones); errors keep the dialog open.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from .derive import DeriveError, compile_predicate

_X = "Demand X"
_Y = "Demand Y"


class FilterConditionDialog(QDialog):
    def __init__(self, columns, parent=None, *, initial: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit filter condition" if initial
                            else "Add filter condition")
        self._columns = list(columns)

        lay = QVBoxLayout(self)

        lay.addWidget(QLabel("Condition (keeps rows where this is true)"))
        self.expr_edit = QPlainTextEdit()
        if initial:
            self.expr_edit.setPlainText(initial)
        self.expr_edit.setPlaceholderText(
            'e.g. [Demand X] >= -32 and [Demand X] <= -28\n'
            '     [MeltVIEW melt pool (mean)] >= 500\n'
            '     [region] == "R1"'
        )
        self.expr_edit.setMinimumHeight(110)
        lay.addWidget(self.expr_edit, 1)

        pick = QHBoxLayout()
        self.col_combo = QComboBox()
        self.col_combo.addItems(self._columns)
        insert = QPushButton("Insert column")
        insert.clicked.connect(self._insert_column)
        pick.addWidget(self.col_combo, 1)
        pick.addWidget(insert)
        lay.addLayout(pick)

        lay.addWidget(self._spatial_box())

        self.error = QLabel("")
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #d9534f;")
        self.error.setVisible(False)
        lay.addWidget(self.error)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

        self.resize(520, 380)

    # -- spatial-box helper --------------------------------------------
    def _spatial_box(self) -> QGroupBox:
        box = QGroupBox("Spatial box (X/Y bounds)")
        grid = QGridLayout(box)

        def spin() -> QDoubleSpinBox:
            s = QDoubleSpinBox()
            s.setRange(-100000.0, 100000.0)
            s.setDecimals(3)
            s.setFixedWidth(100)
            return s

        self.x_min, self.x_max = spin(), spin()
        self.y_min, self.y_max = spin(), spin()
        grid.addWidget(QLabel("X"), 0, 0)
        grid.addWidget(self.x_min, 0, 1)
        grid.addWidget(QLabel("to"), 0, 2)
        grid.addWidget(self.x_max, 0, 3)
        grid.addWidget(QLabel("Y"), 1, 0)
        grid.addWidget(self.y_min, 1, 1)
        grid.addWidget(QLabel("to"), 1, 2)
        grid.addWidget(self.y_max, 1, 3)
        insert = QPushButton("Insert bounds")
        insert.setToolTip("Build the X/Y-range expression into the box above")
        insert.clicked.connect(self._insert_bounds)
        grid.addWidget(insert, 0, 4, 2, 1)
        grid.setColumnStretch(5, 1)
        return box

    def _insert_bounds(self) -> None:
        lo_x, hi_x = sorted((self.x_min.value(), self.x_max.value()))
        lo_y, hi_y = sorted((self.y_min.value(), self.y_max.value()))
        expr = (
            f"[{_X}] >= {lo_x:g} and [{_X}] <= {hi_x:g} "
            f"and [{_Y}] >= {lo_y:g} and [{_Y}] <= {hi_y:g}"
        )
        self.expr_edit.setPlainText(expr)
        self.expr_edit.setFocus()

    def _insert_column(self) -> None:
        name = self.col_combo.currentText()
        if name:
            self.expr_edit.insertPlainText(f"[{name}]")
            self.expr_edit.setFocus()

    # -- accept / result -----------------------------------------------
    def _accept(self) -> None:
        text = self.expr_edit.toPlainText().strip()
        if not text:
            self._show_error("Enter a condition (or Cancel).")
            return
        try:
            compile_predicate(text, self._columns)
        except DeriveError as exc:
            self._show_error(str(exc))
            return
        self.accept()

    def _show_error(self, text: str) -> None:
        self.error.setText(text)
        self.error.setVisible(True)

    def condition(self) -> str:
        return self.expr_edit.toPlainText().strip()
