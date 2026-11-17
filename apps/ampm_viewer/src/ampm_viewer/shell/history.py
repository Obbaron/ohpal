"""Undo / redo history (snapshot-based).

Each committed action stores the shaping state from just *before* and just
*after* it. Undo restores the "before", redo the "after" — no per-action inverse
is ever written, so every action (including lossy ones like remove-derivation or
reset-filters) is undoable by construction.

This module only keeps the two stacks; what a snapshot contains and how it is
captured / restored is owned by :mod:`actions`.
"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QObject, pyqtSignal


@dataclass
class Entry:
    label: str    # human name of the action ("Rename 'A' to 'B'")
    before: dict  # snapshot just before the action
    after: dict   # snapshot just after it


class History(QObject):
    changed = pyqtSignal()  # stacks changed — refresh the Undo/Redo controls

    def __init__(self, limit: int = 50, parent=None) -> None:
        super().__init__(parent)
        self._limit = limit
        self._undo: list[Entry] = []
        self._redo: list[Entry] = []

    # -- recording -----------------------------------------------------
    def push(self, label: str, before: dict, after: dict) -> None:
        """Record a committed action. A new action invalidates the redo stack."""
        self._undo.append(Entry(label, before, after))
        if len(self._undo) > self._limit:
            del self._undo[0]
        self._redo.clear()
        self.changed.emit()

    def clear(self) -> None:
        if self._undo or self._redo:
            self._undo.clear()
            self._redo.clear()
            self.changed.emit()

    # -- queries -------------------------------------------------------
    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo_label(self) -> str:
        return self._undo[-1].label if self._undo else ""

    def redo_label(self) -> str:
        return self._redo[-1].label if self._redo else ""

    # -- stepping (the caller restores the returned entry's snapshot) ---
    def take_undo(self) -> Entry | None:
        if not self._undo:
            return None
        entry = self._undo.pop()
        self._redo.append(entry)
        self.changed.emit()
        return entry

    def take_redo(self) -> Entry | None:
        if not self._redo:
            return None
        entry = self._redo.pop()
        self._undo.append(entry)
        self.changed.emit()
        return entry
