"""Imported first by every scenario: keeps a run away from your real setup.

- Settings go to an INI file in a temp folder (``AMPM_SETTINGS_DIR``; on
  Windows the app would otherwise use the registry).
- The AMPM folder (``AMPM_DATA_DIR``: macros, the plot library, crash
  reports) and Qt's standard folders (Documents, app data, config, cache)
  point into the same temp folder, so nothing is created in your profile.
- No windows on screen: Qt's ``offscreen`` platform, unless the caller set one.
- A dialog nobody answers fails the run: one still open after
  ``MODAL_LIMIT_S`` ends the process with its text, instead of a hang.

``ROOT`` is that temp folder.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

ROOT = Path(tempfile.mkdtemp(prefix="ampm-test-"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["AMPM_SETTINGS_DIR"] = str(ROOT / "settings")
os.environ["AMPM_DATA_DIR"] = str(ROOT / "data" / "AMPM")
os.environ["HOME"] = str(ROOT / "home")          # POSIX: ~ for anything else
(ROOT / "home").mkdir()

from PyQt6.QtCore import QStandardPaths  # noqa: E402  (after the environment)

_APP_SCOPED = {"AppDataLocation", "AppLocalDataLocation", "AppConfigLocation",
               "CacheLocation"}


def _writable(location) -> str:
    """Every writable standard folder, inside ROOT (app-scoped ones keep the
    usual <org>/<app> shape)."""
    path = ROOT / "std" / location.name
    if location.name in _APP_SCOPED:
        path = path / "AMPM" / "AMPM Viewer"
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


QStandardPaths.writableLocation = staticmethod(_writable)


# -- a dialog left waiting for a click ends the run, with its text ----------
import sys  # noqa: E402

from PyQt6.QtCore import QTimer  # noqa: E402
from PyQt6.QtWidgets import QDialog, QLabel  # noqa: E402

MODAL_LIMIT_S = 120
_exec = QDialog.exec


def _guarded_exec(self):
    def stuck() -> None:
        try:
            if not self.isVisible():
                return
            texts = " | ".join(lbl.text() for lbl in self.findChildren(QLabel)
                               if lbl.text())
        except RuntimeError:  # already deleted: it was answered
            return
        sys.stderr.write(
            f"\nA dialog waited {MODAL_LIMIT_S} s for a click nobody will make "
            f"({type(self).__name__}): {texts}\n")
        sys.stderr.flush()
        os._exit(3)

    QTimer.singleShot(MODAL_LIMIT_S * 1000, stuck)
    return _exec(self)


QDialog.exec = _guarded_exec
