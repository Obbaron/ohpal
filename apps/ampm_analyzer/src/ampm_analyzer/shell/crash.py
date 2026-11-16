"""Unexpected errors: written to a report file, shown in a dialog, and the app
kept running.

Without this, PyQt6 ends the app on any error that escapes a button or signal
handler, and the packaged app has no console, so it simply vanishes. ``install``
replaces that with:

- a **report file** per error in the app's data folder (``report_dir``): the
  version, platform, the traceback and the recent log;
- a **dialog** saying what happened, with the report's location, the details,
  and the choice to keep working or quit. One dialog at a time: errors that
  follow while it is open are counted on it (each still gets its report);
- ``fatal.log`` from ``faulthandler`` for crashes Python cannot catch (a
  graphics driver fault), so even those leave a trace.

Errors on worker threads reach the dialog through a queued signal, so it
always opens on the main thread.
"""

from __future__ import annotations

import faulthandler
import platform
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QObject, QStandardPaths, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFont, QGuiApplication, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from .card import DraggableCard

_KEEP_REPORTS = 30       # newest reports kept; older ones are deleted
_LOG_TAIL_LINES = 200    # recent log lines written into a report
_SUMMARY_CHARS = 300     # of the error message, in the dialog

_state: dict = {"bus": None, "notifier": None, "dialog": None, "fatal": None}


def version() -> str:
    try:
        from ampm_analyzer import __version__
        return __version__
    except Exception:  # noqa: BLE001
        return "unknown"


def report_dir() -> Path:
    """Where reports go: the app's local data folder (on Windows,
    ``%LOCALAPPDATA%\\AMPM\\AMPM Analyzer\\crash-reports``)."""
    base = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppLocalDataLocation)
    path = Path(base or Path.home() / ".ampm-analyzer") / "crash-reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _environment() -> str:
    from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR

    return (f"AMPM Analyzer {version()}\n"
            f"Python {sys.version.split()[0]} ({platform.architecture()[0]}), "
            f"Qt {QT_VERSION_STR}, PyQt {PYQT_VERSION_STR}\n"
            f"{platform.platform()}\n"
            f"Frozen: {bool(getattr(sys, 'frozen', False))}")


def _log_tail() -> str:
    bus = _state["bus"]
    if bus is None:
        return ""
    lines = bus.history().splitlines()[-_LOG_TAIL_LINES:]
    return "\n".join(lines)


def write_report(exc_type, exc, tb, where: str = "") -> Path | None:
    """Write one error's report; returns its path (None if it can't be
    written: a report must never raise)."""
    try:
        stamp = datetime.now()
        folder = report_dir()
        path = folder / f"crash-{stamp:%Y%m%d-%H%M%S-%f}.log"
        text = (
            f"{stamp:%Y-%m-%d %H:%M:%S}{f'  ({where})' if where else ''}\n"
            f"{_environment()}\n\n"
            "Traceback\n---------\n"
            + "".join(traceback.format_exception(exc_type, exc, tb))
            + "\nRecent log\n----------\n" + _log_tail() + "\n")
        path.write_text(text, encoding="utf-8")
        for old in sorted(folder.glob("crash-*.log"))[:-_KEEP_REPORTS]:
            old.unlink(missing_ok=True)
        return path
    except Exception:  # noqa: BLE001
        return None


def summary(exc_type, exc) -> str:
    """One line for the dialog: the error's type and message."""
    text = f"{exc_type.__name__}: {exc}" if str(exc) else exc_type.__name__
    text = " ".join(text.split())
    return text if len(text) <= _SUMMARY_CHARS else text[:_SUMMARY_CHARS] + "..."


class _Notifier(QObject):
    """Carries an error to the main thread (queued from a worker thread)."""

    error = pyqtSignal(str, str, str)  # summary, details, report path


class CrashDialog(DraggableCard, QDialog):
    """What went wrong, where the report is, and what to do next."""

    def __init__(self, text: str, details: str, report: str, parent=None,
                 *, startup: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle("Unexpected error")
        self.setModal(True)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.quit_requested = False
        self.more = 0
        self._report = report

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("CrashCard")
        card.setStyleSheet(
            "#CrashCard { background: palette(window); "
            "border: 1px solid palette(mid); border-radius: 10px; }")
        outer.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        title = QLabel("Something went wrong")
        title.setStyleSheet("font-size: 14pt; font-weight: 600;")
        lay.addWidget(title)
        body = QLabel(
            "AMPM Analyzer could not start." if startup else
            "AMPM Analyzer hit an unexpected error. You can keep working, but "
            "save or export anything important, and restart the app if "
            "something looks wrong.")
        body.setWordWrap(True)
        body.setMinimumWidth(440)
        lay.addWidget(body)
        err = QLabel(text)
        err.setWordWrap(True)
        err.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        err.setStyleSheet("font-family: monospace;")
        lay.addWidget(err)
        where = (f"A report was saved to:\n{report}" if report else
                 "The report could not be saved; use Copy details instead.")
        self._where = QLabel(where)
        self._where.setWordWrap(True)
        self._where.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self._where.setStyleSheet("color: palette(placeholder-text);")
        lay.addWidget(self._where)
        self.more_label = QLabel("")
        self.more_label.setVisible(False)
        lay.addWidget(self.more_label)

        self.details = QPlainTextEdit(details)
        self.details.setReadOnly(True)
        self.details.setFont(QFont("monospace", 9))
        self.details.setMinimumHeight(180)
        self.details.setVisible(False)
        lay.addWidget(self.details, 1)

        row = QHBoxLayout()
        self.toggle = QPushButton("Show details")
        self.toggle.clicked.connect(self._toggle_details)
        row.addWidget(self.toggle)
        copy = QPushButton("Copy details")
        copy.clicked.connect(
            lambda: QGuiApplication.clipboard().setText(details))
        row.addWidget(copy)
        if report:
            folder = QPushButton("Open folder")
            folder.clicked.connect(lambda: QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(Path(report).parent))))
            row.addWidget(folder)
        row.addStretch(1)
        quit_btn = QPushButton("Close" if startup else "Quit")
        quit_btn.clicked.connect(self._quit)
        row.addWidget(quit_btn)
        keep = QPushButton("Keep working")
        keep.setVisible(not startup)
        keep.setDefault(True)
        keep.setIcon(QIcon())
        keep.setStyleSheet(
            "QPushButton { background: palette(highlight); "
            "color: palette(highlighted-text); border: none; padding: 6px 20px;"
            " border-radius: 6px; font-weight: 600; }"
            "QPushButton:hover { background: palette(link); }")
        keep.clicked.connect(self.accept)
        row.addWidget(keep)
        lay.addLayout(row)

    def _toggle_details(self) -> None:
        on = not self.details.isVisible()
        self.details.setVisible(on)
        self.toggle.setText("Hide details" if on else "Show details")
        self.adjustSize()

    def _quit(self) -> None:
        self.quit_requested = True
        self.accept()

    def count_another(self) -> None:
        """Another error arrived while this dialog is open."""
        self.more += 1
        s = "" if self.more == 1 else "s"
        self.more_label.setText(
            f"{self.more} more error{s} since this one (each has its own "
            "report in the same folder).")
        self.more_label.setVisible(True)


def _show(text: str, details: str, report: str) -> None:
    """Main thread: show the dialog, or count onto the one already open."""
    app = QApplication.instance()
    if app is None:
        return
    open_dialog = _state["dialog"]
    if open_dialog is not None:
        open_dialog.count_another()
        return
    dialog = CrashDialog(text, details, report, app.activeWindow())
    _state["dialog"] = dialog
    try:
        dialog.exec()
    finally:
        _state["dialog"] = None
    if dialog.quit_requested:
        app.closeAllWindows()
        app.quit()


def handle(exc_type, exc, tb, where: str = "") -> None:
    """Report one unhandled error (any thread)."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return
    details = "".join(traceback.format_exception(exc_type, exc, tb))
    try:  # also into the in-app log
        sys.stderr.write(details)
    except Exception:  # noqa: BLE001
        pass
    path = write_report(exc_type, exc, tb, where)
    notifier = _state["notifier"]
    if notifier is not None:
        notifier.error.emit(summary(exc_type, exc), details,
                            str(path) if path else "")


def _thread_hook(args) -> None:
    if args.exc_type is SystemExit:
        return
    name = args.thread.name if args.thread is not None else "a thread"
    handle(args.exc_type, args.exc_value, args.exc_traceback, f"in {name}")


def install(log_bus=None) -> None:
    """Take over unhandled errors. Call once, on the main thread, after the
    QApplication (and its name) exist."""
    _state["bus"] = log_bus
    notifier = _Notifier()
    notifier.error.connect(_show, Qt.ConnectionType.QueuedConnection)
    _state["notifier"] = notifier
    sys.excepthook = handle
    threading.excepthook = _thread_hook
    try:  # hard crashes: Python's own traceback dump, appended per run
        fatal = open(report_dir() / "fatal.log", "a", encoding="utf-8")
        fatal.write(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} "
                    f"AMPM Analyzer {version()} started ===\n")
        fatal.flush()
        faulthandler.enable(fatal)
        _state["fatal"] = fatal  # keep the file open for the whole run
    except Exception:  # noqa: BLE001 - no fatal log is no reason not to start
        pass


def startup_failed(exc_type, exc, tb) -> None:
    """The app could not even open its window: report it and say so, then
    the caller exits."""
    path = write_report(exc_type, exc, tb, "starting up")
    details = "".join(traceback.format_exception(exc_type, exc, tb))
    if sys.__stderr__ is not None:  # None in the packaged (windowed) app
        sys.__stderr__.write(details)
    if QApplication.instance() is not None:
        CrashDialog(summary(exc_type, exc), details, str(path) if path else "",
                    startup=True).exec()
