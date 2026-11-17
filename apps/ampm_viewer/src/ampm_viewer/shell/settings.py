"""The app's settings store (recent builds, macros, plot-text defaults, theme).

Normally Qt's native store for "AMPM / AMPM Viewer": the registry on Windows
(``HKEY_CURRENT_USER\\Software\\AMPM\\AMPM Viewer``), a ``.conf`` file
elsewhere. When the ``AMPM_SETTINGS_DIR`` environment variable names a folder,
an INI file there is used instead: the tests set it so they never touch your
real settings, and it also gives a portable install its own settings.

Before 2.0.0 the app was named AMPM Analyzer, and kept its settings under that
name; ``carry_over`` brings them across once.
"""

from __future__ import annotations

import os
from pathlib import Path

from PyQt6.QtCore import QSettings

ORG = "AMPM"
APP = "AMPM Viewer"
OLD_APP = "AMPM Analyzer"  # the app's name before 2.0.0 (see carry_over)
ENV_DIR = "AMPM_SETTINGS_DIR"
_CARRIED = "migrated/from_ampm_analyzer"


def app_settings() -> QSettings:
    """The settings store (see the module docstring)."""
    return _store(APP)


def _store(name: str) -> QSettings:
    folder = os.environ.get(ENV_DIR)
    if folder:
        Path(folder).mkdir(parents=True, exist_ok=True)
        return QSettings(str(Path(folder) / f"{name}.ini"),
                         QSettings.Format.IniFormat)
    return QSettings(ORG, name)


def carry_over() -> bool:
    """Once, at the first start under the new name: copy the settings kept
    under the old one (recent builds, Settings choices, plot defaults), and
    keep using the old default macro and plot library folders
    (``Documents/AMPM Analyzer/...``) when they hold files. The old store
    and folders are left as they are. True if anything was carried over."""
    new = app_settings()
    if new.value(_CARRIED, False, type=bool):
        return False
    carried = False
    old = _store(OLD_APP)
    if not new.allKeys():  # nothing chosen under the new name yet
        for key in old.allKeys():
            new.setValue(key, old.value(key))
            carried = True
    from PyQt6.QtCore import QStandardPaths

    docs = Path(QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.DocumentsLocation) or Path.home())
    for key, sub in (("macros/folder", "Macros"),
                     ("plots/library_folder", "Plots")):
        was = docs / OLD_APP / sub
        if not (new.value(key, "") or "") and _holds_files(was):
            new.setValue(key, str(was))
            carried = True
    new.setValue(_CARRIED, True)
    new.sync()
    return carried


def _holds_files(folder: Path) -> bool:
    try:
        return folder.is_dir() and any(folder.iterdir())
    except OSError:
        return False
