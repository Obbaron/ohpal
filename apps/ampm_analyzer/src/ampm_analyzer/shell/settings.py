"""The app's settings store (recent builds, macros, plot-text defaults, theme).

Normally Qt's native store for "AMPM / AMPM Analyzer": the registry on Windows
(``HKEY_CURRENT_USER\\Software\\AMPM\\AMPM Analyzer``), a ``.conf`` file
elsewhere. When the ``AMPM_SETTINGS_DIR`` environment variable names a folder,
an INI file there is used instead: the tests set it so they never touch your
real settings, and it also gives a portable install its own settings.
"""

from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import QSettings

ORG = "AMPM"
APP = "AMPM Analyzer"
ENV_DIR = "AMPM_SETTINGS_DIR"


def app_settings() -> QSettings:
    """The settings store (see the module docstring)."""
    folder = os.environ.get(ENV_DIR)
    if folder:
        Path(folder).mkdir(parents=True, exist_ok=True)
        return QSettings(str(Path(folder) / f"{APP}.ini"),
                         QSettings.Format.IniFormat)
    return QSettings(ORG, APP)
