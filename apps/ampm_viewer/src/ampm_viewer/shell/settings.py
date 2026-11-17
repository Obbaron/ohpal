"""The app's settings store (recent builds, macros, plot-text defaults, theme).

Normally Qt's native store for "AMPM / AMPM Viewer": the registry on Windows
(``HKEY_CURRENT_USER\\Software\\AMPM\\AMPM Viewer``), a ``.conf`` file
elsewhere. When the ``AMPM_SETTINGS_DIR`` environment variable names a folder,
an INI file there is used instead: the tests set it so they never touch your
real settings, and it also gives a portable install its own settings.

Files the app keeps (the macro folder, the plot library, crash reports) live
in one **AMPM folder**, ``data_dir()``: ``%APPDATA%\\AMPM`` on Windows,
``~/Library/Application Support/AMPM`` on macOS and ``$XDG_DATA_HOME/AMPM``
(``~/.local/share/AMPM``) on Linux. ``AMPM_DATA_DIR`` names another folder
(the tests set it).

Before 2.0.0 the app was named AMPM Analyzer, and kept its settings under that
name; ``carry_over`` brings them across once.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PyQt6.QtCore import QSettings

ORG = "AMPM"
APP = "AMPM Viewer"
OLD_APP = "AMPM Analyzer"  # the app's name before 2.0.0 (see carry_over)
ENV_DIR = "AMPM_SETTINGS_DIR"
ENV_DATA = "AMPM_DATA_DIR"
DATA_NAME = "AMPM"
_CARRIED = "migrated/from_ampm_analyzer"


def default_data_dir(platform: str | None = None, env=None,
                     home: Path | None = None) -> Path:
    """The platform's AMPM folder: ``%APPDATA%/AMPM`` (Windows),
    ``~/Library/Application Support/AMPM`` (macOS), ``$XDG_DATA_HOME/AMPM``
    (Linux; ``~/.local/share/AMPM`` when it isn't set)."""
    platform = platform or sys.platform
    env = os.environ if env is None else env
    home = Path(home) if home is not None else Path.home()
    if platform.startswith("win"):
        base = env.get("APPDATA") or home / "AppData" / "Roaming"
    elif platform == "darwin":
        base = home / "Library" / "Application Support"
    else:
        base = env.get("XDG_DATA_HOME") or home / ".local" / "share"
    return Path(base) / DATA_NAME


def data_dir() -> Path:
    """The AMPM folder (``AMPM_DATA_DIR``, else the platform's)."""
    chosen = os.environ.get(ENV_DATA)
    return Path(chosen) if chosen else default_data_dir()


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
    under the old one (recent builds, Settings choices, plot defaults). The
    old store is left as it is. True if anything was carried over."""
    new = app_settings()
    if new.value(_CARRIED, False, type=bool):
        return False
    carried = False
    old = _store(OLD_APP)
    if not new.allKeys():  # nothing chosen under the new name yet
        for key in old.allKeys():
            new.setValue(key, old.value(key))
            carried = True
    new.setValue(_CARRIED, True)
    new.sync()
    return carried
