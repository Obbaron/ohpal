"""Dialog for creating or overwriting a column from a row-wise formula.

The top controls choose the target: a **new** column (named, with an optional
grid position via "After this column") or an **existing** column to
**overwrite**. Columns are referenced in ``[brackets]`` — type ``[`` for an
autocomplete list. The formula is validated live and again on OK.

The dialog is a frameless card (no window chrome) with an accent-coloured
primary button, to match the in-app calculation-editor styling.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon, QPalette
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QRadioButton,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
)

from . import colref
from .derive import _AGGREGATE, _ELEMENTWISE, DeriveError, compile_expr
from .derive_editor import FormulaEdit, FormulaHighlighter
from .widgets import fix_combo

_AT_END = "— at end —"

_PRIMARY_QSS = (
    "QPushButton { background: palette(highlight); color: palette(highlighted-text);"
    " border: none; padding: 6px 20px; border-radius: 6px; font-weight: 600; }"
    "QPushButton:hover { background: palette(link); }"
    "QPushButton:disabled { background: palette(midlight); color: palette(mid); }"
)


class DeriveColumnDialog(QDialog):
    def __init__(self, columns, parent=None, *, taken=None, renames=None) -> None:
        super().__init__(parent)
        self._columns = list(columns)
        self._taken = set(taken or [])
        self._renames = dict(renames or {})

        # Frameless card: drop the window chrome; a translucent window lets the
        # rounded QFrame show its corners.
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("DeriveCard")
        card.setStyleSheet(
            "#DeriveCard { background: palette(window); "
            "border: 1px solid palette(mid); border-radius: 10px; }"
        )
        outer.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        title = QLabel("Create calculation")
        title.setStyleSheet("font-size: 14pt; font-weight: 600;")
        lay.addWidget(title)

        # -- target: new vs overwrite, and placement -------------------
        self.radio_new = QRadioButton("Create new column")
        self.radio_over = QRadioButton("Overwrite existing column")
        self.radio_new.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.radio_new)
        grp.addButton(self.radio_over)
        mode_row = QHBoxLayout()
        mode_row.addWidget(self.radio_new)
        mode_row.addWidget(self.radio_over)
        mode_row.addStretch(1)
        lay.addLayout(mode_row)

        # Left target — stacked: a name field (new) or a column picker (overwrite).
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("new column name")
        self.target_combo = fix_combo(QComboBox())
        self.target_combo.addItems(self._columns)
        self.target_stack = QStackedWidget()
        self.target_stack.addWidget(self.name_edit)     # 0 = new
        self.target_stack.addWidget(self.target_combo)  # 1 = overwrite

        # Right — placement (only meaningful for a new column).
        self.after_label = QLabel("After this column")
        self.after_combo = fix_combo(QComboBox())
        self.after_combo.addItem(_AT_END)
        self.after_combo.addItems(self._columns)

        target_row = QHBoxLayout()
        target_row.addWidget(self.target_stack, 1)
        target_row.addSpacing(12)
        target_row.addWidget(self.after_label)
        target_row.addWidget(self.after_combo)
        lay.addLayout(target_row)

        self.radio_over.toggled.connect(self._sync_mode)

        # -- formula ---------------------------------------------------
        # Header: "Formula" with Functions / Columns insert menus on the right.
        fhdr = QHBoxLayout()
        fhdr.addWidget(QLabel("Formula"))
        fhdr.addStretch(1)
        fhdr.addWidget(self._inserter("Functions", self._function_menu()))
        fhdr.addWidget(self._inserter("Columns", self._column_menu()))
        lay.addLayout(fhdr)

        self.expr_edit = FormulaEdit(self._columns)
        self.expr_edit.setPlaceholderText(colref.resolve_all(
            "e.g. [availability_365] / 365\n"
            "     where([Z] > 0.5, \"high\", \"low\")\n"
            "     mean([mp] where [side] == \"A\") by [part]",
            self._renames,
        ))
        self.expr_edit.setMinimumHeight(140)
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

        self.error = QLabel("")
        self.error.setWordWrap(True)
        self.error.setVisible(False)
        lay.addWidget(self.error)

        # -- buttons (accent primary) ----------------------------------
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText("Run")
        ok.setIcon(QIcon())  # drop the themed check icon
        ok.setDefault(True)
        ok.setStyleSheet(_PRIMARY_QSS)
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setText("Close")
        cancel.setIcon(QIcon())  # drop the themed cross icon
        lay.addWidget(buttons)

        self._sync_mode()
        self.resize(560, 420)

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
        groups = (_AGGREGATE, _ELEMENTWISE, ("where",))
        for i, group in enumerate(groups):
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

    # -- mode handling -------------------------------------------------
    def _sync_mode(self, *_a) -> None:
        over = self.radio_over.isChecked()
        self.target_stack.setCurrentIndex(1 if over else 0)
        self.after_label.setVisible(not over)   # placement is new-column only
        self.after_combo.setVisible(not over)
        self._validate_live()

    def _is_overwrite(self) -> bool:
        return self.radio_over.isChecked()

    def _target_name(self) -> str:
        if self._is_overwrite():
            return self.target_combo.currentText().strip()
        return self.name_edit.text().strip()

    # -- validation ----------------------------------------------------
    def _validate_live(self) -> None:
        """Compile as the user types; amber while in-progress, green when valid.
        The OK handler stays the authoritative check."""
        text = self.expr_edit.toPlainText().strip()
        if not text:
            self.error.setVisible(False)
            return
        # Stay quiet while the formula is visibly mid-entry (unclosed bracket or
        # the completion popup still open).
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
        name = self._target_name()
        if not name:
            self._show_error(
                "Pick a column to overwrite." if self._is_overwrite()
                else "Give the column a name.")
            return
        if not self._is_overwrite() and (
            name in self._columns or name in self._taken
        ):
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

    # -- results -------------------------------------------------------
    def result_values(self) -> tuple[str, str, str]:
        # group is always "" — aggregates scope inline with `by [cols]`.
        return (self._target_name(),
                self.expr_edit.toPlainText().strip(), "")

    def is_overwrite(self) -> bool:
        return self._is_overwrite()

    def after_column(self) -> str | None:
        """The column the new one should follow, or None for end / overwrite."""
        if self._is_overwrite():
            return None
        v = self.after_combo.currentText()
        return None if v == _AT_END else v
