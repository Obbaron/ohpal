"""The app's own title bar, for a frameless main window.

The main window has no native frame: the tab row doubles as the title bar
(drag its empty stretch to move the window, double-click to maximise) and
carries the window buttons. This module holds the three pieces that replace
what the native frame did:

- ``TitleBar``      the row itself: move on drag, maximise on double-click.
- ``WindowButtons`` minimise / maximise-restore / close.
- ``ResizeGrips``   thin invisible strips along the window's edges and corners
                    that resize it.

Moving and resizing are handed to the system (``startSystemMove`` /
``startSystemResize``), so edge snapping keeps working.
"""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import QHBoxLayout, QToolButton, QWidget

from . import icons

BAR_HEIGHT = 34          # px; also the height of the window buttons
_BUTTON_WIDTH = 46
_CLOSE_RED = "#e81123"   # the usual close-button hover colour
_EDGE = 4                # px: resize strip thickness
_CORNER = 8              # px: corner resize square


def toggle_maximized(window: QWidget) -> None:
    """Maximise the window, or restore it when it already is."""
    if window.isMaximized():
        window.showNormal()
    else:
        window.showMaximized()


class TitleBar(QWidget):
    """A row that moves the window when its empty area is dragged and
    maximises / restores it on a double-click. Buttons and tabs placed in it
    take their own clicks; only what reaches the bar itself counts."""

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.button() == Qt.MouseButton.LeftButton and self._start_move():
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            toggle_maximized(self.window())
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _start_move(self) -> bool:
        handle = self.window().windowHandle()
        return bool(handle is not None and handle.startSystemMove())


class _CloseButton(QToolButton):
    """Close: red on hover, with a white icon while it is."""

    def __init__(self) -> None:
        super().__init__()
        self._color = "#000000"

    def retint(self, color: str) -> None:
        self._color = color
        self.setIcon(icons.ui("win_close", color))

    def enterEvent(self, event) -> None:  # noqa: N802
        self.setIcon(icons.ui("win_close", "#ffffff"))
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.setIcon(icons.ui("win_close", self._color))
        super().leaveEvent(event)


class WindowButtons(QWidget):
    """Minimise, maximise / restore, close: flush to the bar's top-right."""

    def __init__(self, window: QWidget, color: str) -> None:
        super().__init__()
        self._window = window
        self._color = color
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.setStyleSheet(
            "QToolButton { border: none; border-radius: 0; padding: 0;"
            " background: transparent; }"
            "QToolButton:hover { background: palette(midlight); }"
            "QToolButton:pressed { background: palette(mid); }"
            f"QToolButton#WinClose:hover {{ background: {_CLOSE_RED}; }}"
            "QToolButton#WinClose:pressed { background: #b50d1c; }"
        )
        self.min_btn = QToolButton()
        self.max_btn = QToolButton()
        self.close_btn = _CloseButton()
        self.close_btn.setObjectName("WinClose")
        for btn in (self.min_btn, self.max_btn, self.close_btn):
            btn.setFixedSize(_BUTTON_WIDTH, BAR_HEIGHT)
            btn.setIconSize(QSize(16, 16))
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            lay.addWidget(btn)
        self.min_btn.setToolTip("Minimise")
        self.close_btn.setToolTip("Close")
        self.min_btn.clicked.connect(window.showMinimized)
        self.max_btn.clicked.connect(lambda: toggle_maximized(window))
        self.close_btn.clicked.connect(window.close)
        self.retint(color)

    def retint(self, color: str) -> None:
        """Redraw the icons in ``color`` (a theme switch)."""
        self._color = color
        self.min_btn.setIcon(icons.ui("win_min", color))
        self.close_btn.retint(color)
        self.sync()

    def sync(self) -> None:
        """Show maximise or restore, to match the window's state."""
        maximized = self._window.isMaximized()
        self.max_btn.setIcon(
            icons.ui("win_restore" if maximized else "win_max", self._color))
        self.max_btn.setToolTip("Restore" if maximized else "Maximise")


class _Grip(QWidget):
    """One invisible resize strip. Pressing it starts a system resize from
    its edge(s)."""

    def __init__(self, window: QWidget, edges, cursor) -> None:
        super().__init__(window)
        self._edges = edges
        self.setCursor(cursor)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        handle = self.window().windowHandle()
        if event.button() == Qt.MouseButton.LeftButton and handle is not None:
            handle.startSystemResize(self._edges)
            event.accept()
            return
        super().mousePressEvent(event)


class ResizeGrips:
    """Eight grips around a frameless window: its edges and corners. They sit
    on top of the window's content and are hidden while it is maximised."""

    def __init__(self, window: QWidget) -> None:
        self._window = window
        e, c = Qt.Edge, Qt.CursorShape
        self._grips = {
            name: _Grip(window, edges, cursor) for name, edges, cursor in (
                ("left", e.LeftEdge, c.SizeHorCursor),
                ("right", e.RightEdge, c.SizeHorCursor),
                ("top", e.TopEdge, c.SizeVerCursor),
                ("bottom", e.BottomEdge, c.SizeVerCursor),
                ("top_left", e.TopEdge | e.LeftEdge, c.SizeFDiagCursor),
                ("bottom_right", e.BottomEdge | e.RightEdge, c.SizeFDiagCursor),
                ("top_right", e.TopEdge | e.RightEdge, c.SizeBDiagCursor),
                ("bottom_left", e.BottomEdge | e.LeftEdge, c.SizeBDiagCursor),
            )}
        self.place()

    def grips(self) -> dict:
        return dict(self._grips)

    def place(self) -> None:
        """Lay the grips along the window's current edges and keep them on
        top; hide them while the window is maximised (nothing to resize)."""
        w, h = self._window.width(), self._window.height()
        t, k = _EDGE, _CORNER
        g = self._grips
        g["left"].setGeometry(0, k, t, max(0, h - 2 * k))
        g["right"].setGeometry(w - t, k, t, max(0, h - 2 * k))
        g["top"].setGeometry(k, 0, max(0, w - 2 * k), t)
        g["bottom"].setGeometry(k, h - t, max(0, w - 2 * k), t)
        g["top_left"].setGeometry(0, 0, k, k)
        g["top_right"].setGeometry(w - k, 0, k, k)
        g["bottom_left"].setGeometry(0, h - k, k, k)
        g["bottom_right"].setGeometry(w - k, h - k, k, k)
        show = not (self._window.isMaximized() or self._window.isFullScreen())
        for grip in g.values():
            grip.setVisible(show)
            if show:
                grip.raise_()
