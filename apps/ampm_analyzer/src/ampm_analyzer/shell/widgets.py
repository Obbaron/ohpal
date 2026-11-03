"""Small shared widget helpers."""

from __future__ import annotations

from PyQt6.QtWidgets import QComboBox, QListView


def fix_combo(cb: QComboBox) -> QComboBox:
    """Give a combo a plain ``QListView`` popup and return it.

    Under the app's Fusion style + global stylesheet, the default styled
    popup view fails to close on click (and swallows the selection); a plain
    ``QListView`` restores normal click-to-select-and-close behaviour.
    """
    cb.setView(QListView())
    return cb
