"""A frameless-card message box matching the app's dialog styling.

The native ``QMessageBox`` has its own window chrome and sits apart from the
in-app dialogs (calculation, filter, export, …). ``CardMessage`` mirrors their
look — a frameless rounded card, a bold title, and an accent primary button —
so confirmations and notices (new-build overwrite, "create a DataStore?", …)
read as part of the same family.

Use the module helpers rather than the class directly:

    if ask(parent, "DataStore", "Overwrite it?", ok_text="Overwrite"):
        ...
    tell(parent, "Part assignment", "Not implemented yet.")
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
    QVBoxLayout,
)

# Mirror of derive_dialog._PRIMARY_QSS — accent primary button via palette roles.
_PRIMARY_QSS = (
    "QPushButton { background: palette(highlight); color: palette(highlighted-text);"
    " border: none; padding: 6px 20px; border-radius: 6px; font-weight: 600; }"
    "QPushButton:hover { background: palette(link); }"
    "QPushButton:disabled { background: palette(midlight); color: palette(mid); }"
)


class CardMessage(QDialog):
    """A frameless-card confirm / notice dialog.

    ``confirm=True`` shows an accent primary button plus a secondary one and
    returns via ``exec()`` (Accepted / Rejected); otherwise it's a single-button
    acknowledgement.
    """

    def __init__(self, title: str, text: str, parent=None, *, confirm: bool = False,
                 ok_text: str | None = None, cancel_text: str = "Close") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)

        # Frameless card (matches the calculation / filter / export dialogs).
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("MessageCard")
        card.setStyleSheet(
            "#MessageCard { background: palette(window); "
            "border: 1px solid palette(mid); border-radius: 10px; }"
        )
        outer.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("font-size: 14pt; font-weight: 600;")
        lay.addWidget(title_lbl)

        body = QLabel(text)
        body.setWordWrap(True)
        body.setMinimumWidth(320)
        lay.addWidget(body)

        if confirm:
            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok
                | QDialogButtonBox.StandardButton.Cancel
            )
            buttons.rejected.connect(self.reject)
            cancel = buttons.button(QDialogButtonBox.StandardButton.Cancel)
            cancel.setText(cancel_text)
            cancel.setIcon(QIcon())
        else:
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText(ok_text or ("Yes" if confirm else "OK"))
        ok.setIcon(QIcon())
        ok.setDefault(True)
        ok.setStyleSheet(_PRIMARY_QSS)
        lay.addWidget(buttons)


def ask(parent, title: str, text: str, *, ok_text: str = "Yes",
        cancel_text: str = "No") -> bool:
    """Show a confirm dialog; return True if the primary button was chosen."""
    dlg = CardMessage(title, text, parent, confirm=True,
                      ok_text=ok_text, cancel_text=cancel_text)
    return dlg.exec() == QDialog.DialogCode.Accepted


def tell(parent, title: str, text: str, *, ok_text: str = "OK") -> None:
    """Show a single-button acknowledgement dialog."""
    CardMessage(title, text, parent, confirm=False, ok_text=ok_text).exec()
