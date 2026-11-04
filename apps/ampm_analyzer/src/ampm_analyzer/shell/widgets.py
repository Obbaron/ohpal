"""Small shared widget helpers."""

from __future__ import annotations

from PyQt6.QtWidgets import QComboBox


def fix_combo(cb: QComboBox) -> QComboBox:
    """Pass a combo through unchanged (native behaviour).

    This used to swap in a plain ``QListView`` popup to work around a supposed
    "popup won't close on click" bug under the app's Fusion style + global
    stylesheet. That evidence came from the headless/offscreen Qt platform,
    which can't render real popups — so the bug may never have existed in a
    real X11 session, and the view-swap (replacing Qt's purpose-built
    ``QComboBoxListView`` with a generic list) may itself have been what broke
    closing. We're now letting combos behave natively to find out.

    Kept as a wrapper (rather than removing all 18 call sites) so the fix is a
    one-line revert if native closing really does fail here. If it does, the
    proper fix is scoping the stylesheet off combo popups, not per-combo hacks.
    """
    return cb
