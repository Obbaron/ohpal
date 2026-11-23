"""The main window's keyboard shortcuts, in one table.

``window.MainWindow`` binds each one to its action (``QShortcut``), the
toolbars put the keys in their buttons' tooltips (``tip``), and the help
page "Keyboard shortcuts" lists the same table. Keys are written the Qt way
("Ctrl+B"); on a Mac, Qt reads Ctrl as Command, and ``native`` shows them so.

Pure description apart from ``native``: no widgets.
"""

from __future__ import annotations

# name -> (keys, what it does). Several keys for one name: the first is shown.
SHORTCUTS: dict[str, tuple[tuple[str, ...], str]] = {
    "panel": (("Ctrl+B",), "Show or hide the side panel"),
    "open": (("Ctrl+O",), "Open a build"),
    "close": (("Ctrl+W",), "Close the build and every plot (File > Close)"),
    "settings": (("Ctrl+,",), "Settings"),
    "help": (("F1",), "Help"),
    "undo": (("Ctrl+Z",), "Undo"),
    "redo": (("Ctrl+Shift+Z", "Ctrl+Y"), "Redo"),
    "next_tab": (("Ctrl+Tab", "Ctrl+PgDown"), "Next tab"),
    "prev_tab": (("Ctrl+Shift+Tab", "Ctrl+PgUp"), "Previous tab"),
    "layer_next": (("Alt+Down",), "Next layer (Data tab, layer viewer)"),
    "layer_prev": (("Alt+Up",), "Previous layer (Data tab, layer viewer)"),
    "rename": (("F2",), "Rename the selected column"),
    "filter": (("Ctrl+F",), "Filter"),
    "new_plot": (("Ctrl+N",), "New plot"),
    "export": (("Ctrl+E",), "Export to Excel"),
    "reset_view": (("Ctrl+0",), "Reset the plot's view"),
    "screenshot": (("Ctrl+Shift+S",), "Screenshot of the plot"),
}

# Plot toolbar controls (``plotcontrols.Control.key``) that have a shortcut.
CONTROL_SHORTCUT = {"reset_view": "reset_view", "screenshot": "screenshot",
                    "layer_prev": "layer_prev", "layer_next": "layer_next"}


def keys(name: str) -> tuple[str, ...]:
    return SHORTCUTS[name][0]


def native(name: str) -> str:
    """The first key of ``name`` as this platform writes it (``⌘B`` on a Mac)."""
    from PyQt6.QtGui import QKeySequence

    return QKeySequence(keys(name)[0]).toString(
        QKeySequence.SequenceFormat.NativeText)


def tip(text: str, name: str | None) -> str:
    """A tooltip with the shortcut after it: ``Filter (Ctrl+F)``."""
    if not name or name not in SHORTCUTS:
        return text
    return f"{text} ({native(name)})"
