"""Dialog for defining a row-wise derived column (name + formula).

Columns are referenced in the formula in ``[brackets]`` — type ``[`` for an
autocomplete list. The formula is validated live and again on OK against the
available columns; errors are shown inline and keep the dialog open.
"""

from __future__ import annotations

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from .derive import DeriveError, compile_expr
from .derive_editor import FormulaEdit, FormulaHighlighter


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

        # Multi-line formula box (supports long / nested formulas), with syntax
        # highlighting + column/function autocomplete (type '[' for columns).
        lay.addWidget(QLabel("Formula"))
        self.expr_edit = FormulaEdit(self._columns)
        self.expr_edit.setPlaceholderText(
            "e.g. cov([LaserVIEW (mean)])\n"
            "     where([Z] > 0.5, \"high\", \"low\")\n"
            "     mean([mp] where [side] == \"A\") by [part]"
        )
        self.expr_edit.setMinimumHeight(150)
        dark = self.palette().color(QPalette.ColorRole.Window).lightness() < 128
        self._highlighter = FormulaHighlighter(
            self.expr_edit.document(), self._columns, dark=dark)
        lay.addWidget(self.expr_edit, 1)

        # Live validation: debounce typing, then compile against the columns and
        # report inline (amber while in-progress, green when valid).
        self._live = QTimer(self)
        self._live.setSingleShot(True)
        self._live.setInterval(250)
        self._live.timeout.connect(self._validate_live)
        self.expr_edit.textChanged.connect(lambda: self._live.start())

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

    def _validate_live(self) -> None:
        """Compile as the user types; amber for in-progress problems, green when
        the formula is valid. The OK handler stays the authoritative check."""
        text = self.expr_edit.toPlainText().strip()
        if not text:
            self.error.setVisible(False)
            return
        # Don't nag while the formula is visibly mid-entry: an unclosed bracket
        # (you're picking a column) or the completion popup still open. Wait for
        # it to settle before reporting anything.
        if text.count("[") != text.count("]") or self.expr_edit.completer_active():
            self.error.setVisible(False)
            return
        try:
            compile_expr(text, self._columns)
        except DeriveError as exc:
            self._set_status(str(exc), "warn")
        except Exception as exc:  # noqa: BLE001 — never let typing raise
            self._set_status(str(exc), "warn")
        else:
            self._set_status("✓ valid expression", "ok")

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

    _STATUS_COLOR = {"error": "#d9534f", "warn": "#c08a2e", "ok": "#3c9a5f"}

    def _set_status(self, text: str, level: str) -> None:
        self.error.setStyleSheet(f"color: {self._STATUS_COLOR[level]};")
        self.error.setText(text)
        self.error.setVisible(True)

    def _show_error(self, text: str) -> None:
        self._set_status(text, "error")

    def result_values(self) -> tuple[str, str, str]:
        # group is always "" now — scope aggregates inline with `by [cols]`.
        return (self.name_edit.text().strip(),
                self.expr_edit.toPlainText().strip(), "")
