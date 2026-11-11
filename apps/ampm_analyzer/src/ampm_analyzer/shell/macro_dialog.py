"""Macro popups: the step preview shown before a macro runs, and the issues list
shown when it can't run. Both are frameless cards, like the other dialogs."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QLabel,
    QListWidget,
    QVBoxLayout,
)

# Mirror of derive_dialog._PRIMARY_QSS — accent primary button via palette roles.
_PRIMARY_QSS = (
    "QPushButton { background: palette(highlight); color: palette(highlighted-text);"
    " border: none; padding: 6px 20px; border-radius: 6px; font-weight: 600; }"
    "QPushButton:hover { background: palette(link); }"
    "QPushButton:disabled { background: palette(midlight); color: palette(mid); }"
)


class _ListCard(QDialog):
    """A frameless card: title, a line of context, a read-only numbered list."""

    def __init__(self, title: str, intro: str, lines: list[str], parent=None, *,
                 ok_text: str, cancel_text: str | None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setModal(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("MacroCard")
        card.setStyleSheet(
            "#MacroCard { background: palette(window); "
            "border: 1px solid palette(mid); border-radius: 10px; }"
        )
        outer.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("font-size: 14pt; font-weight: 600;")
        lay.addWidget(title_lbl)

        intro_lbl = QLabel(intro)
        intro_lbl.setWordWrap(True)
        lay.addWidget(intro_lbl)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list.setWordWrap(True)
        self.list.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.list.addItems(lines)
        lay.addWidget(self.list, 1)

        flags = QDialogButtonBox.StandardButton.Ok
        if cancel_text is not None:
            flags |= QDialogButtonBox.StandardButton.Cancel
        buttons = QDialogButtonBox(flags)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText(ok_text)
        ok.setIcon(QIcon())
        ok.setDefault(True)
        ok.setStyleSheet(_PRIMARY_QSS)
        if cancel_text is not None:
            cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
            cancel.setText(cancel_text)
            cancel.setIcon(QIcon())
        lay.addWidget(buttons)
        self.resize(560, 420)


class MacroPreviewDialog(_ListCard):
    """What a macro will do, step by step, before it runs."""

    def __init__(self, name: str, descriptions: list[str], parent=None) -> None:
        n = len(descriptions)
        super().__init__(
            f"Run macro '{name}'",
            f"{n} step{'s' if n != 1 else ''}, applied together — if any step "
            "can't be applied, nothing is changed.",
            [f"{i}.  {d}" for i, d in enumerate(descriptions, 1)],
            parent, ok_text="Run", cancel_text="Cancel",
        )


class MacroIssuesDialog(_ListCard):
    """Why a macro didn't run. Nothing was changed."""

    def __init__(self, name: str, issues: list[str], parent=None) -> None:
        super().__init__(
            "Macro issues",
            f"'{name}' was not run and nothing was changed.",
            issues, parent, ok_text="OK", cancel_text=None,
        )
        self.resize(560, 300)
