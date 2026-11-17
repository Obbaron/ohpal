"""Shared behaviour of the app's frameless "card" popups.

The dialogs and tool windows (calculation, filter, export, messages, help,
log, ...) have no native title bar, so there is nothing to grab them by.
``DraggableCard`` gives it back: press on any part of the card that is not a
control (the title, a label, the background) and drag to move it. A window
that can be resized (the log, help) calls ``enable_resize``: its edges and
corners then resize it, and a grip sits in the card's corner.

Use it as the first base class::

    class FilterConditionDialog(DraggableCard, QDialog): ...
"""

from __future__ import annotations

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtWidgets import QSizeGrip

# Cursor over each edge / corner of a resizable card.
_CURSORS = {
    Qt.Edge.LeftEdge: Qt.CursorShape.SizeHorCursor,
    Qt.Edge.RightEdge: Qt.CursorShape.SizeHorCursor,
    Qt.Edge.TopEdge: Qt.CursorShape.SizeVerCursor,
    Qt.Edge.BottomEdge: Qt.CursorShape.SizeVerCursor,
}


class DraggableCard:
    """Mixin: drag a frameless card by its inert areas.

    Buttons, fields, lists and other controls take their own mouse presses, so
    only a press that falls through to the card itself starts a move. The move
    is handed to the system when it can be (which keeps edge snapping); where
    it cannot, the card follows the pointer itself.
    """

    _drag_offset = None  # pointer position inside the card, while dragging
    _resize_rim = 0      # px around the card that resize the window (0: none)
    _resizing = None     # (edges, pointer start, geometry start) while resizing
    _grip = None         # the corner grip, in the card's own corner
    _grip_card = None

    # -- resizing (windows that opt in: enable_resize) ------------------------
    def enable_resize(self, outer_layout, card, rim: int = 6) -> None:
        """Let the window be resized from its edges and corners, and put a
        grip in the card's bottom-right corner. ``outer_layout`` holds
        ``card``: it gets a clear ``rim`` around the card to grab (the window
        needs a translucent background)."""
        self._resize_rim = rim
        outer_layout.setContentsMargins(rim, rim, rim, rim)
        self.setMouseTracking(True)
        self._grip_card = card
        self._grip = QSizeGrip(card)
        self._grip.setFixedSize(14, 14)
        self._grip.setToolTip("Drag to resize")
        self._place_grip()

    def _place_grip(self) -> None:
        if self._grip is None:
            return
        # From the window's size: the card fills it less the rim (the card
        # itself may not have been laid out yet).
        w = self.width() - 2 * self._resize_rim
        h = self.height() - 2 * self._resize_rim
        self._grip.move(w - self._grip.width() - 3, h - self._grip.height() - 3)
        self._grip.raise_()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._place_grip()

    def _edges_at(self, pos) -> Qt.Edge:
        """The window edges under ``pos`` (corners reach a little further,
        so they're easy to catch)."""
        edges = Qt.Edge(0)
        m = self._resize_rim
        if not m:
            return edges
        r, x, y, c = self.rect(), pos.x(), pos.y(), 2 * m
        near_l, near_r = x <= m, x >= r.width() - m
        near_t, near_b = y <= m, y >= r.height() - m
        if near_l or near_r:  # a corner too, within reach along the edge
            near_t = near_t or y <= c
            near_b = near_b or y >= r.height() - c
        if near_t or near_b:
            near_l = near_l or x <= c
            near_r = near_r or x >= r.width() - c
        if near_l:
            edges |= Qt.Edge.LeftEdge
        if near_r:
            edges |= Qt.Edge.RightEdge
        if near_t:
            edges |= Qt.Edge.TopEdge
        if near_b:
            edges |= Qt.Edge.BottomEdge
        return edges

    @staticmethod
    def _edge_cursor(edges):
        lt = Qt.Edge.LeftEdge | Qt.Edge.TopEdge
        rb = Qt.Edge.RightEdge | Qt.Edge.BottomEdge
        rt = Qt.Edge.RightEdge | Qt.Edge.TopEdge
        lb = Qt.Edge.LeftEdge | Qt.Edge.BottomEdge
        if edges in (lt, rb):
            return Qt.CursorShape.SizeFDiagCursor
        if edges in (rt, lb):
            return Qt.CursorShape.SizeBDiagCursor
        return _CURSORS.get(edges)

    def _resize_to(self, global_pos) -> None:
        edges, start, geo = self._resizing
        d = global_pos - start
        r = QRect(geo)
        mw, mh = self.minimumWidth(), self.minimumHeight()
        # (QRect's right / bottom are inclusive: a width w spans w - 1.)
        if edges & Qt.Edge.LeftEdge:
            r.setLeft(min(geo.left() + d.x(), geo.right() - mw + 1))
        if edges & Qt.Edge.RightEdge:
            r.setRight(max(geo.right() + d.x(), geo.left() + mw - 1))
        if edges & Qt.Edge.TopEdge:
            r.setTop(min(geo.top() + d.y(), geo.bottom() - mh + 1))
        if edges & Qt.Edge.BottomEdge:
            r.setBottom(max(geo.bottom() + d.y(), geo.top() + mh - 1))
        self.setGeometry(r)

    # -- moving --------------------------------------------------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.button() == Qt.MouseButton.LeftButton:
            edges = self._edges_at(event.position().toPoint())
            if edges:  # an edge or corner: resize (the system's, if it can)
                handle = self.windowHandle()
                if handle is None or not handle.startSystemResize(edges):
                    self._resizing = (edges, event.globalPosition().toPoint(),
                                      self.geometry())
                event.accept()
                return
            if not self._start_system_move():
                self._drag_offset = (event.globalPosition().toPoint()
                                     - self.frameGeometry().topLeft())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._resizing is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._resize_to(event.globalPosition().toPoint())
            event.accept()
            return
        if self._resize_rim and not event.buttons():
            shape = self._edge_cursor(self._edges_at(event.position().toPoint()))
            if shape is None:
                self.unsetCursor()
            else:
                self.setCursor(shape)
        if (self._drag_offset is not None
                and event.buttons() & Qt.MouseButton.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_offset = None
        self._resizing = None
        super().mouseReleaseEvent(event)

    def _start_system_move(self) -> bool:
        handle = self.windowHandle()
        return bool(handle is not None and handle.startSystemMove())
