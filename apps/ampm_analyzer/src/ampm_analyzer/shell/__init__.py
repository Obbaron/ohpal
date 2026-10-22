"""New AMPM Analyzer GUI shell (PyQt6).

The overhauled in-app layout: File / Data / Plot tabs, a context-swapping
toolbar, a docked side panel, and a status bar, with VisPy for in-app 3D
visualisation.

Deliberately *not wired up* yet — every control is present but inert so the
layout can be tweaked freely. Only structural navigation (opening tabs,
swapping the toolbar) is live. Actions are connected to the existing analysis
logic in a later pass.

Run it with:  python -m ampm_analyzer.shell
"""

from .app import main

__all__ = ["main"]
