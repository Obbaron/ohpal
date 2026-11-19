"""Application entry point for the new shell.

Mirrors the existing app's conventions (organization/application name, window
icon loaded from packaged assets) so it launches the same way.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QEvent
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from . import crash
from .logconsole import LogBus, StreamTee
from .theme import apply_theme, initial_scheme


# The app icon (every size in the .ico, so the title bar, taskbar and
# Alt+Tab each get a sharp one). Next to the package, in the bundle too.
ICON = Path(__file__).resolve().parent.parent / "assets" / "ampm.ico"


def _app_icon() -> QIcon:
    icon = QIcon(str(ICON)) if ICON.is_file() else QIcon()
    return icon  # an empty icon if missing: cosmetic, never fatal


def _windows_app_id() -> None:
    """On Windows, give the process its own taskbar identity, so the taskbar
    shows the app's icon (not Python's, when run from source) and groups its
    windows together."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "AMPM.AMPMViewer")
    except Exception:  # noqa: BLE001 - cosmetic
        pass


class _App(QApplication):
    """The application, plus the files macOS asks it to open (a double-
    clicked ``.ampmplot``: a ``FileOpen`` event, not the command line). They
    wait in ``pending`` until the window is up, then go to ``open_files``."""

    def __init__(self, argv) -> None:
        super().__init__(argv)
        self.pending: list[str] = []
        self.open_files = None   # set once the window exists

    def event(self, e) -> bool:
        if e.type() == QEvent.Type.FileOpen and e.file():
            if self.open_files is not None:
                self.open_files([e.file()])
            else:
                self.pending.append(e.file())
            return True
        return super().event(e)


def main() -> None:
    _windows_app_id()
    app = _App(sys.argv)
    # Started with a file (Windows / Linux: a double-clicked .ampmplot) while
    # the app is running: that copy opens it and this one ends here.
    from . import single_instance

    files = [str(Path(f).resolve()) for f in single_instance.openable(sys.argv[1:])]
    if files and single_instance.forward(files):
        sys.exit(0)
    app.setWindowIcon(_app_icon())  # every window: main, plots, help, log
    app.setOrganizationName("AMPM")
    app.setApplicationName("AMPM Viewer")
    app.setApplicationVersion(crash.version())
    apply_theme(app, initial_scheme(app))  # follow the OS light/dark at launch

    # Capture console output (incl. ohpal's prints) into the in-app log.
    log_bus = LogBus()
    sys.stdout = StreamTee(log_bus, sys.stdout)
    sys.stderr = StreamTee(log_bus, sys.stderr)
    # From here an unexpected error is reported (file + dialog) instead of
    # ending the app without a word.
    crash.install(log_bus)

    try:
        from .window import MainWindow

        window = MainWindow(log_bus=log_bus)
        window.setWindowIcon(_app_icon())
        window.show()
    except Exception:  # noqa: BLE001 - no window: report it, then stop
        crash.startup_failed(*sys.exc_info())
        sys.exit(1)

    # Files from the command line or from macOS, and later ones another start
    # hands over, open in the window. File > Close puts a new window in the
    # old one's place (MainWindow.relaunch): follow it.
    current = [window]

    def adopt(new) -> None:
        current[0] = new
        app.open_files = new.open_files
        new.relaunched.connect(adopt)

    window.relaunched.connect(adopt)
    app.open_files = window.open_files
    listener = single_instance.Listener(  # noqa: F841
        lambda paths: current[0].open_files(paths), app)
    if files or app.pending:
        window.open_files(files + app.pending)
        app.pending.clear()

    sys.exit(app.exec())
