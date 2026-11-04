"""A formula editor for the derive/label/filter DSL: syntax highlighting plus
column/function autocompletion.

Two reusable pieces:

* ``FormulaHighlighter`` — colours columns, functions, keywords, numbers and
  strings, and flags a *closed* ``[column]`` whose name isn't in the build (so a
  typo shows up red without half-typed names flickering).
* ``FormulaEdit`` — a ``QPlainTextEdit`` with a completer. Typing ``[`` offers
  the column names; typing an identifier offers functions/keywords. Picking a
  column closes the bracket; picking a function opens a paren.

Both read the token sets straight from :mod:`derive`, so they can't drift from
what the parser actually accepts.
"""

from __future__ import annotations

import re

from PyQt6.QtCore import QStringListModel, Qt
from PyQt6.QtGui import (
    QColor,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
)
from PyQt6.QtWidgets import QCompleter, QPlainTextEdit

from .derive import _AGGREGATE, _ELEMENTWISE

_FUNCTIONS = sorted({*_AGGREGATE, *_ELEMENTWISE, "where"})
_KEYWORDS = ["and", "or", "not", "by"]

# VS Code-ish token palettes, one per theme (chosen for contrast on each base).
_LIGHT = {
    "column": "#0b66c3", "unknown": "#c0392b", "function": "#795e26",
    "keyword": "#8e24aa", "number": "#098658", "string": "#a31515",
}
_DARK = {
    "column": "#9cdcfe", "unknown": "#f48771", "function": "#dcdcaa",
    "keyword": "#c586c0", "number": "#b5cea8", "string": "#ce9178",
}


def _fmt(hex_color: str, *, bold: bool = False, underline: bool = False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(hex_color))
    if bold:
        f.setFontWeight(700)
    if underline:
        f.setFontUnderline(True)
        f.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
        f.setUnderlineColor(QColor(hex_color))
    return f


class FormulaHighlighter(QSyntaxHighlighter):
    """Colour DSL tokens; wave-underline unknown closed ``[columns]``."""

    def __init__(self, document, columns, *, dark: bool) -> None:
        super().__init__(document)
        self._known = set(columns)
        c = _DARK if dark else _LIGHT
        self._f_column = _fmt(c["column"])
        self._f_unknown = _fmt(c["unknown"], underline=True)
        self._f_function = _fmt(c["function"])
        self._f_keyword = _fmt(c["keyword"], bold=True)
        self._f_number = _fmt(c["number"])
        self._f_string = _fmt(c["string"])
        # Precompiled, applied in order; columns last so bracket colour wins
        # over any function/keyword word that happens to sit inside a name.
        name_alt = "|".join(re.escape(w) for w in _FUNCTIONS)
        kw_alt = "|".join(re.escape(w) for w in _KEYWORDS)
        self._rules = [
            (re.compile(r'"[^"]*"'), self._f_string),
            (re.compile(r"\b\d+\.?\d*\b"), self._f_number),
            (re.compile(rf"\b(?:{name_alt})\b"), self._f_function),
            (re.compile(rf"\b(?:{kw_alt})\b"), self._f_keyword),
        ]
        self._col_re = re.compile(r"\[([^\[\]]*)\]")

    def set_columns(self, columns) -> None:
        self._known = set(columns)
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:  # noqa: N802 (Qt override)
        for rx, fmt in self._rules:
            for m in rx.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)
        # Column refs last: a known name reads as a column, an unknown one is
        # wave-underlined. Only closed [..] match, so half-typed names are calm.
        for m in self._col_re.finditer(text):
            name = m.group(1).strip()
            fmt = self._f_column if name in self._known else self._f_unknown
            self.setFormat(m.start(), m.end() - m.start(), fmt)


class FormulaEdit(QPlainTextEdit):
    """Plain-text formula box with column/function autocompletion."""

    _ident_tail = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")

    def __init__(self, columns, parent=None) -> None:
        super().__init__(parent)
        self._columns = list(columns)
        self._completer = QCompleter(self)
        self._completer.setWidget(self)
        self._completer.setCompletionMode(
            QCompleter.CompletionMode.PopupCompletion)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setModel(QStringListModel(self))
        self._completer.activated[str].connect(self._insert_completion)

    def set_columns(self, columns) -> None:
        self._columns = list(columns)

    def completer_active(self) -> bool:
        """True while the completion popup is open (mid-token entry)."""
        return self._completer.popup().isVisible()

    # -- completion context -------------------------------------------
    def _context(self):
        """('col'|'id', prefix, start_index) for the token under the cursor, or
        None. 'col' = inside an unclosed ``[``; 'id' = a bare identifier."""
        end = self.textCursor().position()
        before = self.toPlainText()[:end]
        lb, rb = before.rfind("["), before.rfind("]")
        if lb > rb:  # an unclosed '[' -> completing a column name
            return ("col", before[lb + 1:], lb + 1)
        m = self._ident_tail.search(before)
        if m:
            return ("id", m.group(0), m.start())
        return None

    def _candidates(self, kind: str) -> list[str]:
        return self._columns if kind == "col" else [*_FUNCTIONS, *_KEYWORDS]

    # -- key handling -------------------------------------------------
    def keyPressEvent(self, e) -> None:  # noqa: N802 (Qt override)
        popup = self._completer.popup()
        if popup.isVisible() and e.key() in (
            Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Escape,
            Qt.Key.Key_Tab, Qt.Key.Key_Backtab,
        ):
            e.ignore()  # let the popup accept/dismiss
            return
        super().keyPressEvent(e)
        self._maybe_complete()

    def _maybe_complete(self) -> None:
        ctx = self._context()
        if ctx is None:
            self._completer.popup().hide()
            return
        kind, prefix, _start = ctx
        if kind == "id" and not prefix:
            self._completer.popup().hide()
            return
        model = self._completer.model()
        model.setStringList(self._candidates(kind))
        self._completer.setCompletionPrefix(prefix)
        if self._completer.completionCount() == 0:
            self._completer.popup().hide()
            return
        popup = self._completer.popup()
        popup.setCurrentIndex(self._completer.completionModel().index(0, 0))
        rect = self.cursorRect()
        rect.setWidth(
            popup.sizeHintForColumn(0)
            + popup.verticalScrollBar().sizeHint().width()
        )
        self._completer.complete(rect)

    def _insert_completion(self, text: str) -> None:
        ctx = self._context()
        if ctx is None:
            return
        kind, _prefix, start = ctx
        doc = self.toPlainText()
        cur = self.textCursor()
        end = cur.position()
        cur.setPosition(start)
        cur.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        if kind == "col":
            closing = "" if doc[end:end + 1] == "]" else "]"
            cur.insertText(text + closing)
        elif text in _FUNCTIONS:
            cur.insertText(text + "(")
        else:
            cur.insertText(text + " ")
        self.setTextCursor(cur)
        self._completer.popup().hide()
