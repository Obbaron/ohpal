"""Quick per-part calculation: reduce a signal within each part into a column.

A small shortcut over the full calculation dialog — pick a signal and a
reducer, and it adds a derived column ``<reducer>([signal]) by [part_id]``
(the part column is whatever ``part_id`` is currently renamed to). Styled as a
frameless card to match the other dialogs.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from .widgets import fix_combo

# Mirror of derive_dialog._PRIMARY_QSS — accent primary button via palette roles.
_PRIMARY_QSS = (
    "QPushButton { background: palette(highlight); color: palette(highlighted-text);"
    " border: none; padding: 6px 20px; border-radius: 6px; font-weight: 600; }"
    "QPushButton:hover { background: palette(link); }"
    "QPushButton:disabled { background: palette(midlight); color: palette(mid); }"
)

# (label, derive-function) — all are aggregate functions the derive DSL knows.
_REDUCERS = (
    ("Mean", "mean"), ("Median", "median"), ("Std dev", "std"),
    ("Variance", "var"), ("CoV", "cov"), ("Min", "min"),
    ("Max", "max"), ("Sum", "sum"),
)


class PartCalcDialog(QDialog):
    def __init__(self, columns, part_col: str, parent=None, *, taken=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Per-part calculation")
        self._columns = list(columns)
        self._part_col = part_col
        self._taken = set(taken or [])
        self._name_edited = False

        # Frameless card (matches the calculation / filter dialogs).
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("PartCalcCard")
        card.setStyleSheet(
            "#PartCalcCard { background: palette(window); "
            "border: 1px solid palette(mid); border-radius: 10px; }"
        )
        outer.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        title = QLabel("Per-part calculation")
        title.setStyleSheet("font-size: 14pt; font-weight: 600;")
        lay.addWidget(title)

        form = QFormLayout()
        self.signal_combo = fix_combo(QComboBox())
        self.signal_combo.addItems(self._columns)
        form.addRow("Signal", self.signal_combo)

        self.reduce_combo = fix_combo(QComboBox())
        for label, _fn in _REDUCERS:
            self.reduce_combo.addItem(label)
        form.addRow("Reduce", self.reduce_combo)

        self.name_edit = QLineEdit()
        form.addRow("Name", self.name_edit)
        lay.addLayout(form)

        self.error = QLabel("")
        self.error.setWordWrap(True)
        self.error.setVisible(False)
        self.error.setStyleSheet("color: #d9534f;")
        lay.addWidget(self.error)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText("Add")
        ok.setIcon(QIcon())
        ok.setDefault(True)
        ok.setStyleSheet(_PRIMARY_QSS)
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setText("Close")
        cancel.setIcon(QIcon())
        lay.addWidget(buttons)

        # Auto-fill the name from signal + reducer until the user edits it.
        self.name_edit.textEdited.connect(lambda _t: setattr(self, "_name_edited", True))
        self.signal_combo.currentTextChanged.connect(lambda _t: self._sync_name())
        self.reduce_combo.currentTextChanged.connect(lambda _t: self._sync_name())
        self._sync_name()
        self.setMinimumWidth(440)

    # -- name ----------------------------------------------------------
    def _reducer(self) -> str:
        i = self.reduce_combo.currentIndex()
        return _REDUCERS[i][1] if 0 <= i < len(_REDUCERS) else "mean"

    def _default_name(self) -> str:
        sig = self.signal_combo.currentText()
        label = self.reduce_combo.currentText().lower()
        return f"{sig} ({label}/part)" if sig else ""

    def _sync_name(self) -> None:
        if not self._name_edited:
            self.name_edit.setText(self._default_name())

    # -- result --------------------------------------------------------
    def _accept(self) -> None:
        name = self.name_edit.text().strip() or self._default_name()
        if not name:
            self._show_error("Give the column a name.")
            return
        if name in self._columns or name in self._taken:
            self._show_error(f"A column named {name!r} already exists.")
            return
        if not self.signal_combo.currentText():
            self._show_error("Pick a signal.")
            return
        self.accept()

    def _show_error(self, text: str) -> None:
        self.error.setText(text)
        self.error.setVisible(True)

    def result_values(self) -> tuple[str, str, str]:
        """(name, signal, reducer-function)."""
        return (
            self.name_edit.text().strip() or self._default_name(),
            self.signal_combo.currentText(),
            self._reducer(),
        )
