"""Dialog for adding a row filter condition.

A condition is a boolean predicate in the same DSL as derived columns, e.g.
``[Demand X] >= -32 and [Demand X] <= -28``. Columns are referenced in
``[brackets]`` — type ``[`` for an autocomplete list. A "Spatial box" helper
fills the common X/Y-bounds case. The condition is validated live and again on
OK against the available columns (including derived ones).

Styled to match the calculation / label dialogs: a frameless card with an
accent-coloured primary button, syntax highlighting and autocomplete, and
Functions / Columns insert menus.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon, QPalette
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QToolButton,
    QVBoxLayout,
)

from .derive import _AGGREGATE, _ELEMENTWISE, DeriveError, compile_predicate
from .derive_editor import FormulaEdit, FormulaHighlighter

_X = "Demand X"
_Y = "Demand Y"

# Mirror of derive_dialog._PRIMARY_QSS — accent primary button via palette roles.
_PRIMARY_QSS = (
    "QPushButton { background: palette(highlight); color: palette(highlighted-text);"
    " border: none; padding: 6px 20px; border-radius: 6px; font-weight: 600; }"
    "QPushButton:hover { background: palette(link); }"
    "QPushButton:disabled { background: palette(midlight); color: palette(mid); }"
)


class FilterConditionDialog(QDialog):
    def __init__(self, columns, parent=None, *, initial: str = "",
                 renames=None) -> None:
        super().__init__(parent)
        self._columns = list(columns)
        self._renames = dict(renames or {})

        # Frameless card (matches the calculation / label dialogs).
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("FilterCard")
        card.setStyleSheet(
            "#FilterCard { background: palette(window); "
            "border: 1px solid palette(mid); border-radius: 10px; }"
        )
        outer.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        title = QLabel("Edit filter" if initial else "Add filter")
        title.setStyleSheet("font-size: 14pt; font-weight: 600;")
        lay.addWidget(title)

        # Condition header: label + Functions / Columns insert menus.
        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("Condition (keeps rows where this is true)"))
        hdr.addStretch(1)
        hdr.addWidget(self._inserter("Functions", self._function_menu()))
        hdr.addWidget(self._inserter("Columns", self._column_menu()))
        lay.addLayout(hdr)

        self.expr_edit = FormulaEdit(self._columns)
        if initial:
            self.expr_edit.setPlainText(initial)
        self.expr_edit.setPlaceholderText(
            'e.g. [Demand X] >= -32 and [Demand X] <= -28\n'
            '     [MeltVIEW melt pool (mean)] >= 500\n'
            '     [region] == "R1"'
        )
        self.expr_edit.setMinimumHeight(110)
        dark = self.palette().color(QPalette.ColorRole.Window).lightness() < 128
        self._highlighter = FormulaHighlighter(
            self.expr_edit.document(), self._columns, dark=dark)
        lay.addWidget(self.expr_edit, 1)

        # Live validation (debounced).
        self._live = QTimer(self)
        self._live.setSingleShot(True)
        self._live.setInterval(250)
        self._live.timeout.connect(self._validate_live)
        self.expr_edit.textChanged.connect(lambda: self._live.start())

        lay.addWidget(self._spatial_box())

        self.error = QLabel("")
        self.error.setWordWrap(True)
        self.error.setVisible(False)
        lay.addWidget(self.error)

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
        lay.addWidget(buttons)

        self.resize(540, 400)

    # -- Functions / Columns insert menus ------------------------------
    def _inserter(self, label: str, menu: QMenu) -> QToolButton:
        btn = QToolButton()
        btn.setText(label)
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        btn.setAutoRaise(True)
        btn.setMenu(menu)
        return btn

    def _function_menu(self) -> QMenu:
        m = QMenu(self)
        for i, group in enumerate((_AGGREGATE, _ELEMENTWISE, ("where",))):
            if i:
                m.addSeparator()
            for name in group:
                m.addAction(name).triggered.connect(
                    lambda _c=False, n=name: self._insert(f"{n}("))
        return m

    def _column_menu(self) -> QMenu:
        m = QMenu(self)
        for name in self._columns:
            m.addAction(name).triggered.connect(
                lambda _c=False, n=name: self._insert(f"[{n}]"))
        return m

    def _insert(self, text: str) -> None:
        self.expr_edit.insertPlainText(text)
        self.expr_edit.setFocus()

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
        x = self._renames.get(_X, _X)  # follow a renamed Demand X / Demand Y
        y = self._renames.get(_Y, _Y)
        expr = (
            f"[{x}] >= {lo_x:g} and [{x}] <= {hi_x:g} "
            f"and [{y}] >= {lo_y:g} and [{y}] <= {hi_y:g}"
        )
        self.expr_edit.setPlainText(expr)
        self.expr_edit.setFocus()

    # -- validation ----------------------------------------------------
    def _validate_live(self) -> None:
        """Compile as the user types; amber while in-progress, green when valid.
        The OK handler stays the authoritative check."""
        text = self.expr_edit.toPlainText().strip()
        if not text:
            self.error.setVisible(False)
            return
        # Stay quiet while the condition is visibly mid-entry (unclosed bracket
        # or the completion popup still open).
        if text.count("[") != text.count("]") or self.expr_edit.completer_active():
            self.error.setVisible(False)
            return
        try:
            compile_predicate(text, self._columns)
        except DeriveError as exc:
            self._set_status(str(exc), "warn")
        except Exception as exc:  # noqa: BLE001 — never let typing raise
            self._set_status(str(exc), "warn")
        else:
            self._set_status("✓ valid condition", "ok")

    def _accept(self) -> None:
        text = self.expr_edit.toPlainText().strip()
        if not text:
            self._show_error("Enter a condition (or Close).")
            return
        try:
            compile_predicate(text, self._columns)
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

    def condition(self) -> str:
        return self.expr_edit.toPlainText().strip()
