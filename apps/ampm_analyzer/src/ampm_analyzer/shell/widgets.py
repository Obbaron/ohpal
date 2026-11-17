"""Small shared widget helpers."""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtWidgets import QComboBox


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
