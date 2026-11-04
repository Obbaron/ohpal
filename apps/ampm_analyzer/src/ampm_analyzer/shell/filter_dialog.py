"""Dialog for adding a row filter condition.

A condition is a boolean predicate in the same DSL as derived columns, e.g.
``[Demand X] >= -32 and [Demand X] <= -28``. Columns are referenced in
``[brackets]`` — type ``[`` for an autocomplete list. A scrollable column of
common **templates** (previews of the filter text) seeds the box on click. The
condition is validated live and again on OK against the available columns
(including derived ones).

Styled to match the calculation / label dialogs: a frameless card with an
accent-coloured primary button, syntax highlighting, autocomplete, and
Functions / Columns insert menus.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon, QPalette
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import colref
from .derive import _AGGREGATE, _ELEMENTWISE, DeriveError, compile_predicate
from .derive_editor import FormulaEdit, FormulaHighlighter

# Common filter templates (raw column names; resolved through the rename map
# before display). Each is a preview the user clicks to seed the editor.
_TEMPLATES = [
    ("Spatial box + layer",
     "[Demand X] >= -32 and [Demand X] <= -28 and "
     "[Demand Y] >= -8 and [Demand Y] <= -7 and [layer] == 1"),
    ("Value threshold", "[MeltVIEW melt pool (mean)] >= 500"),
    ("Category match", '[region] == "R1"'),
    ("Z range", "0 < [Z] and [Z] < 1"),
    ("Single layer", "[layer] == 1"),
]

# Mirror of derive_dialog._PRIMARY_QSS — accent primary button via palette roles.
_PRIMARY_QSS = (
    "QPushButton { background: palette(highlight); color: palette(highlighted-text);"
    " border: none; padding: 6px 20px; border-radius: 6px; font-weight: 600; }"
    "QPushButton:hover { background: palette(link); }"
    "QPushButton:disabled { background: palette(midlight); color: palette(mid); }"
)


class _TemplateCard(QFrame):
    """A clickable preview of a filter template; emits its text on click."""

    clicked = pyqtSignal(str)

    def __init__(self, name: str, text: str) -> None:
        super().__init__()
        self._text = text
        self.setObjectName("TplCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            "#TplCard { border: 1px solid palette(mid); border-radius: 6px; "
            "background: palette(base); } "
            "#TplCard:hover { border: 1px solid palette(highlight); }"
        )
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 6, 8, 6)
        v.setSpacing(2)
        head = QLabel(name)
        head.setStyleSheet("font-weight: 600; font-size: 9pt;")
        preview = QLabel(text)
        preview.setWordWrap(True)
        preview.setStyleSheet(
            "font-family: monospace; font-size: 8.5pt; "
            "color: palette(placeholder-text);")
        v.addWidget(head)
        v.addWidget(preview)

    def mousePressEvent(self, e) -> None:  # noqa: N802 (Qt override)
        self.clicked.emit(self._text)


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

        body = QHBoxLayout()
        body.setSpacing(12)
        body.addWidget(self._templates_column())

        # Right side: condition header + editor + inline status.
        right = QVBoxLayout()
        right.setSpacing(8)
        hdr = QHBoxLayout()
        hdr.addWidget(QLabel("Condition (keeps rows where this is true)"))
        hdr.addStretch(1)
        hdr.addWidget(self._inserter("Functions", self._function_menu()))
        hdr.addWidget(self._inserter("Columns", self._column_menu()))
        right.addLayout(hdr)

        self.expr_edit = FormulaEdit(self._columns)
        if initial:
            self.expr_edit.setPlainText(initial)
        self.expr_edit.setPlaceholderText(
            "e.g. click a template on the left, or type a condition — "
            "columns in [brackets], type [ to autocomplete"
        )
        dark = self.palette().color(QPalette.ColorRole.Window).lightness() < 128
        self._highlighter = FormulaHighlighter(
            self.expr_edit.document(), self._columns, dark=dark)
        right.addWidget(self.expr_edit, 1)

        self.error = QLabel("")
        self.error.setWordWrap(True)
        self.error.setVisible(False)
        right.addWidget(self.error)
        body.addLayout(right, 1)
        lay.addLayout(body, 1)

        # Live validation (debounced).
        self._live = QTimer(self)
        self._live.setSingleShot(True)
        self._live.setInterval(250)
        self._live.timeout.connect(self._validate_live)
        self.expr_edit.textChanged.connect(lambda: self._live.start())

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText("Filter")
        ok.setIcon(QIcon())
        ok.setDefault(True)
        ok.setStyleSheet(_PRIMARY_QSS)
        cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel.setText("Close")
        cancel.setIcon(QIcon())
        # Bottom row: "Clear" on the left, Filter / Close on the right.
        clear = QPushButton("Clear")
        clear.setToolTip("Clear the condition")
        clear.clicked.connect(lambda: self.expr_edit.setPlainText(""))
        bottom = QHBoxLayout()
        bottom.addWidget(clear)
        bottom.addStretch(1)
        bottom.addWidget(buttons)
        lay.addLayout(bottom)

        self.resize(820, 520)

    # -- templates column ----------------------------------------------
    def _templates_column(self) -> QWidget:
        col = QWidget()
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        v.addWidget(QLabel("Templates"))
        inner = QVBoxLayout()
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(6)
        for name, raw in _TEMPLATES:
            card = _TemplateCard(name, self._resolve(raw))
            card.clicked.connect(self._apply_template)
            inner.addWidget(card)
        inner.addStretch(1)
        holder = QWidget()
        holder.setLayout(inner)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(holder)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setFixedWidth(230)
        v.addWidget(scroll, 1)
        return col

    def _resolve(self, text: str) -> str:
        """Map a template's raw column names to their current display names."""
        for orig, disp in self._renames.items():
            text = colref.rewrite_refs(text, orig, disp)
        return text

    def _apply_template(self, text: str) -> None:
        self.expr_edit.setPlainText(text)
        self.expr_edit.setFocus()

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

    # -- validation ----------------------------------------------------
    def _validate_live(self) -> None:
        """Compile as the user types; amber while in-progress, green when valid.
        The OK handler stays the authoritative check."""
        text = self.expr_edit.toPlainText().strip()
        if not text:
            self.error.setVisible(False)
            return
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
