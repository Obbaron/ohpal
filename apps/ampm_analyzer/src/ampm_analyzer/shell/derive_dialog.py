"""Dialog for defining a row-wise derived column (name + formula).

Columns are inserted into the formula in ``[brackets]`` (click Insert or type
them). The formula is validated on OK against the available columns; errors are
shown inline and keep the dialog open.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from .derive import DeriveError, compile_expr


class DeriveColumnDialog(QDialog):
    def __init__(self, columns, parent=None, *, taken=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Derive column")
        self._columns = list(columns)
        self._taken = set(taken or [])

        lay = QVBoxLayout(self)

        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("new column name")
        form.addRow("Name", self.name_edit)

        lay.addLayout(form)

        # Multi-line formula box (supports long / nested formulas).
        lay.addWidget(QLabel("Formula"))
        self.expr_edit = QPlainTextEdit()
        self.expr_edit.setPlaceholderText(
            "e.g. cov([LaserVIEW (mean)])\n"
            "     where([Z] > 0.5, \"high\", \"low\")\n"
            "     mean([mp] where [side] == \"A\") by [part]"
        )
        self.expr_edit.setMinimumHeight(150)
        lay.addWidget(self.expr_edit, 1)

        pick = QHBoxLayout()
        self.col_combo = QComboBox()
        self.col_combo.addItems(self._columns)
        insert = QPushButton("Insert column")
        insert.clicked.connect(self._insert_column)
        pick.addWidget(self.col_combo, 1)
        pick.addWidget(insert)
        lay.addLayout(pick)

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

        self.resize(520, 360)

    def _insert_column(self) -> None:
        name = self.col_combo.currentText()
        if name:
            self.expr_edit.insertPlainText(f"[{name}]")
            self.expr_edit.setFocus()

    def _accept(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            self._show_error("Give the column a name.")
            return
        if name in self._columns or name in self._taken:
            self._show_error(f"A column named {name!r} already exists.")
            return
        try:
            compile_expr(self.expr_edit.toPlainText(), self._columns)
        except DeriveError as exc:
            self._show_error(str(exc))
            return
        self.accept()

    def _show_error(self, text: str) -> None:
        self.error.setText(text)
        self.error.setVisible(True)

    def result_values(self) -> tuple[str, str, str]:
        # group is always "" now — scope aggregates inline with `by [cols]`.
        return (self.name_edit.text().strip(),
                self.expr_edit.toPlainText().strip(), "")
