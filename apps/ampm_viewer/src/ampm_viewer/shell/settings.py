"""The app's settings store (recent builds, macros, plot-text defaults, theme).

Settings are kept in ``AMPM Viewer.conf`` (an INI file) in the AMPM folder,
beside everything else the app keeps. When the ``AMPM_SETTINGS_DIR``
environment variable names a folder, an INI file there is used instead: the
tests set it so they never touch your real settings.

Files the app keeps (the settings, the macro folder, the plot library, the
default builds folder, crash reports) live in one **AMPM folder**,
``data_dir()``: ``%APPDATA%\\AMPM`` on Windows,
``~/Library/Application Support/AMPM`` on macOS and ``$XDG_DATA_HOME/AMPM``
(``~/.local/share/AMPM``) on Linux. ``AMPM_DATA_DIR`` names another folder
(the tests set it).

Settings used to live in Qt's native store (the registry on Windows,
``~/.config/AMPM`` elsewhere), and before 2.0.0 under the app's old name, AMPM
Analyzer; ``carry_over`` brings them into the file once.
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


def settings_file() -> Path:
    """Where the settings are kept: ``AMPM Viewer.conf`` in the AMPM folder
    (or ``AMPM Viewer.ini`` in ``AMPM_SETTINGS_DIR``)."""
    folder = os.environ.get(ENV_DIR)
    if folder:
        return Path(folder) / f"{APP}.ini"
    return data_dir() / f"{APP}.conf"


def _store(name: str) -> QSettings:
    folder = os.environ.get(ENV_DIR)
    path = (Path(folder) / f"{name}.ini" if folder
            else data_dir() / f"{name}.conf")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return QSettings(str(path), QSettings.Format.IniFormat)


def _earlier_stores() -> list[QSettings]:
    """Where settings were kept before, newest first: Qt's native store under
    this name, then under the old one (with ``AMPM_SETTINGS_DIR``: the old
    name's INI file beside the new one)."""
    if os.environ.get(ENV_DIR):
        return [_store(OLD_APP)]
    return [QSettings(ORG, APP), QSettings(ORG, OLD_APP)]


def default_builds_dir() -> Path:
    """``Builds`` in the AMPM folder: where New and Open start when there's
    no recent build and no builds folder chosen in Settings."""
    return data_dir() / "Builds"


def carry_over() -> bool:
    """Once, at the first start with the settings file: copy the settings
    kept where they used to be (recent builds, Settings choices, plot
    defaults), from the newest place that has any. The old stores are left as
    they are. True if anything was carried over."""
    new = app_settings()
    if new.value(_CARRIED, False, type=bool):
        return False
    carried = False
    if not new.allKeys():  # nothing kept in the file yet
        for old in _earlier_stores():
            keys = old.allKeys()
            for key in keys:
                new.setValue(key, old.value(key))
            if keys:
                carried = True
                break
    new.setValue(_CARRIED, True)
    new.sync()
    return carried
