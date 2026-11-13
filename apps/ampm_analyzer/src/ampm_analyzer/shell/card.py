"""Shared behaviour of the app's frameless "card" popups.

The dialogs and tool windows (calculation, filter, export, messages, help,
log, ...) have no native title bar, so there is nothing to grab them by.
``DraggableCard`` gives it back: press on any part of the card that is not a
control (the title, a label, the background) and drag to move it.

Use it as the first base class::

    class FilterConditionDialog(DraggableCard, QDialog): ...
"""

from __future__ import annotations

from PyQt6.QtCore import Qt


class DraggableCard:
    """Mixin: drag a frameless card by its inert areas.

    Buttons, fields, lists and other controls take their own mouse presses, so
    only a press that falls through to the card itself starts a move. The move
    is handed to the system when it can be (which keeps edge snapping); where
    it cannot, the card follows the pointer itself.
    """

    _drag_offset = None  # pointer position inside the card, while dragging

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.button() == Qt.MouseButton.LeftButton:
            if not self._start_system_move():
                self._drag_offset = (event.globalPosition().toPoint()
                                     - self.frameGeometry().topLeft())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if (self._drag_offset is not None
                and event.buttons() & Qt.MouseButton.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def _start_system_move(self) -> bool:
        handle = self.windowHandle()
        return bool(handle is not None and handle.startSystemMove())
