"""Small shared widget helpers."""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QStyle,
    QStyleOptionGroupBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


def fix_combo(cb: QComboBox) -> QComboBox:
    """Pass a combo through unchanged, and return it.

    This was once a workaround for "combo popup won't close on click". That
    turned out to be a WSLg/XWayland bug, not ours: a bare-Qt repro (no app
    code, with and without our Fusion style + stylesheet) showed QComboBox
    popups failing to grab/dismiss, while QMenu popups behaved — classic
    Wayland popup-grab failure under WSLg. It does not occur on native Windows
    (the shipped build) or a normal X11/Wayland desktop. For WSL dev, force the
    platform instead: ``QT_QPA_PLATFORM=xcb``.

    Kept as a no-op wrapper so the 18 call sites stay tidy and so there's an
    obvious place to hang a real per-combo fix if one is ever needed.
    """
    return cb


class _BlankClick(QObject):
    def __init__(self, widget, callback) -> None:
        super().__init__(widget)
        self._widget, self._callback = widget, callback

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt override)
        # A press reaches the widget itself only on its bare background (or
        # passed up from a label, a separator, a spacer): controls take
        # their own.
        if obj is self._widget and event.type() == QEvent.Type.MouseButtonPress:
            self._callback()
        return False  # just observe


def on_blank_click(widget, callback) -> None:
    """Call ``callback`` when ``widget``'s empty space is clicked (used to
    deselect by clicking an empty part of a toolbar)."""
    widget.installEventFilter(_BlankClick(widget, callback))


class CollapsibleGroup(QGroupBox):
    """A group box whose title folds it: click the title to hide or show its
    contents (a ▾ / ▸ marks which). Lay the contents out on ``body``."""

    expandedChanged = pyqtSignal(bool)

    def __init__(self, title: str, parent=None, *, expanded: bool = True) -> None:
        super().__init__(parent)
        self._text = title
        self.setMouseTracking(True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.body = QWidget()
        outer.addWidget(self.body)
        self._expanded = True
        self.set_expanded(expanded)

    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = bool(expanded)
        self.body.setVisible(self._expanded)
        self.setTitle(f"{'▾' if self._expanded else '▸'}  {self._text}")
        self.expandedChanged.emit(self._expanded)

    def _on_title(self, pos) -> bool:
        opt = QStyleOptionGroupBox()
        self.initStyleOption(opt)
        label = self.style().subControlRect(
            QStyle.ComplexControl.CC_GroupBox, opt,
            QStyle.SubControl.SC_GroupBoxLabel, self)
        # The whole strip the title sits in, so it's an easy target.
        return pos.y() <= label.bottom() + 2

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if (event.button() == Qt.MouseButton.LeftButton
                and self._on_title(event.position().toPoint())):
            self.set_expanded(not self._expanded)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        on = self._on_title(event.position().toPoint())
        self.setCursor(Qt.CursorShape.PointingHandCursor if on
                       else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)


class Disclosure(QWidget):
    """A small fold-out section: a ▸ / ▾ button with a title, and ``body``
    below it, shown when open."""

    expandedChanged = pyqtSignal(bool)

    def __init__(self, title: str, parent=None, *, expanded: bool = False) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self._text = title
        self.button = QToolButton()
        self.button.setCheckable(True)
        self.button.setAutoRaise(True)
        self.button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.toggled.connect(self.set_expanded)
        lay.addWidget(self.button, 0, Qt.AlignmentFlag.AlignLeft)
        self.body = QWidget()
        lay.addWidget(self.body)
        self._expanded = None
        self.set_expanded(expanded)

    def is_expanded(self) -> bool:
        return bool(self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        expanded = bool(expanded)
        if expanded == self._expanded:
            return
        self._expanded = expanded
        self.button.blockSignals(True)
        self.button.setChecked(expanded)
        self.button.blockSignals(False)
        self.button.setText(f"{'▾' if expanded else '▸'}  {self._text}")
        self.body.setVisible(expanded)
        self.expandedChanged.emit(expanded)
