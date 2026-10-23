"""Application entry point for the new shell.

Mirrors the existing app's conventions (organization/application name, window
icon loaded from packaged assets) so it launches the same way.
"""

from __future__ import annotations

import sys
from importlib.resources import files

from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import QApplication

from .theme import apply_theme, initial_scheme
from .window import MainWindow


def _app_icon() -> QIcon:
    try:
        data = files("ampm_analyzer").joinpath("assets", "ampm.ico").read_bytes()
        pixmap = QPixmap()
        pixmap.loadFromData(data)
        return QIcon(pixmap)
    except Exception:  # noqa: BLE001 - icon is cosmetic
        return QIcon()


def main() -> None:
    app = QApplication(sys.argv)
    app.setOrganizationName("AMPM")
    app.setApplicationName("AMPM Analyzer")
    apply_theme(app, initial_scheme(app))  # follow the OS light/dark at launch

    window = MainWindow()
    window.setWindowIcon(_app_icon())
    window.show()

    sys.exit(app.exec())
