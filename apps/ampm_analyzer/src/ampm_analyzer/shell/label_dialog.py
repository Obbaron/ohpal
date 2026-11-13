"""Dialog for defining a label column from if/elif/else rules.

Each rule is a boolean condition and a text label; the first matching rule wins,
and rows matching none get the default label. Conditions reference columns in
[brackets] and use comparisons with and / or / not. Validated on OK.

Styled to match the calculation dialog: a frameless card with an accent-coloured
primary button, and the rules listed directly (no surrounding box).
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .card import DraggableCard
from . import colref
from .derive import DeriveError, compile_predicate

# Mirror of derive_dialog._PRIMARY_QSS — accent primary button via palette roles.
_PRIMARY_QSS = (
    "QPushButton { background: palette(highlight); color: palette(highlighted-text);"
    " border: none; padding: 6px 20px; border-radius: 6px; font-weight: 600; }"
    "QPushButton:hover { background: palette(link); }"
    "QPushButton:disabled { background: palette(midlight); color: palette(mid); }"
)


class _Rule(QWidget):
    def __init__(self, on_remove, placeholder: str = "") -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.cond = QLineEdit()
        self.cond.setPlaceholderText(
            placeholder or "[Demand X] > 30 and [Demand Y] < -21")
        self.label = QLineEdit()
        self.label.setPlaceholderText("label")
        self.label.setFixedWidth(120)
        rm = QToolButton()
        rm.setText("✕")
        rm.setAutoRaise(True)
        rm.clicked.connect(lambda: on_remove(self))
        row.addWidget(QLabel("if"))
        row.addWidget(self.cond, 1)
        row.addWidget(QLabel("→"))
        row.addWidget(self.label)
        row.addWidget(rm)


class GroupLabelDialog(DraggableCard, QDialog):
    def __init__(self, columns, parent=None, *, taken=None, renames=None) -> None:
        super().__init__(parent)
        self._columns = list(columns)
        self._taken = set(taken or [])
        self._rules: list[_Rule] = []
        self._cond_ph = colref.resolve_all(  # rename-aware rule placeholder
            "[Demand X] > 30 and [Demand Y] < -21", renames)

        # Frameless card (matches the calculation dialog).
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("LabelCard")
        card.setStyleSheet(
            "#LabelCard { background: palette(window); "
            "border: 1px solid palette(mid); border-radius: 10px; }"
        )
        outer.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        title = QLabel("Create label")
        title.setStyleSheet("font-size: 14pt; font-weight: 600;")
        lay.addWidget(title)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("new column name")
        name_row.addWidget(self.name_edit, 1)
        lay.addLayout(name_row)

        lay.addWidget(QLabel("Rules"))

        # Rules listed directly — no surrounding box / scroll area.
        self._rules_box = QVBoxLayout()
        self._rules_box.setContentsMargins(0, 0, 0, 0)
        self._rules_box.setSpacing(4)
        lay.addLayout(self._rules_box)

        default_row = QHBoxLayout()
        default_row.addWidget(QLabel("Otherwise"))
        self.default_edit = QLineEdit()
        self.default_edit.setPlaceholderText("default label for the rest")
        default_row.addWidget(self.default_edit, 1)
        lay.addLayout(default_row)

        self.error = QLabel("")
        self.error.setWordWrap(True)
        self.error.setVisible(False)
        lay.addWidget(self.error)

        # Bottom row: "Add rule" on the left, Run / Close on the right.
        add_rule = QPushButton("Add rule")
        add_rule.clicked.connect(lambda: self._add_rule())
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText("Run")
        ok.setIcon(QIcon())
        ok.setDefault(True)
        ok.setStyleSheet(_PRIMARY_QSS)
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setText("Close")
        cancel.setIcon(QIcon())
        bottom = QHBoxLayout()
        bottom.addWidget(add_rule)
        bottom.addStretch(1)
        bottom.addWidget(buttons)
        lay.addLayout(bottom)

        self._add_rule()  # start with one empty rule
        self.resize(560, self.sizeHint().height())

    # -- rule rows -----------------------------------------------------
    def _add_rule(self) -> _Rule:
        rule = _Rule(self._remove_rule, self._cond_ph)
        self._rules.append(rule)
        self._rules_box.addWidget(rule)
        return rule

    def _remove_rule(self, rule: _Rule) -> None:
        if len(self._rules) <= 1:
            return  # keep at least one
        self._rules.remove(rule)
        self._rules_box.removeWidget(rule)
        rule.deleteLater()

    # -- result --------------------------------------------------------
    def _accept(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            self._show_error("Give the column a name.")
            return
        if name in self._columns or name in self._taken:
            self._show_error(f"A column named {name!r} already exists.")
            return
        rules = self.rules()
        if not rules:
            self._show_error("Add at least one rule with a condition and a label.")
            return
        for r in rules:
            try:
                compile_predicate(r["cond"], self._columns)
            except DeriveError as exc:
                self._show_error(f"Rule “{r['label'] or '?'}”: {exc}")
                return
        self.accept()

    def _show_error(self, text: str) -> None:
        self.error.setStyleSheet("color: #d9534f;")
        self.error.setText(text)
        self.error.setVisible(True)

    def rules(self) -> list[dict]:
        out = []
        for r in self._rules:
            cond = r.cond.text().strip()
            label = r.label.text().strip()
            if cond and label:
                out.append({"cond": cond, "label": label})
        return out

    def result_values(self) -> tuple[str, list[dict], str]:
        return (
            self.name_edit.text().strip(),
            self.rules(),
            self.default_edit.text().strip(),
        )
