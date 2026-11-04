"""Small shared widget helpers."""

from __future__ import annotations

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
