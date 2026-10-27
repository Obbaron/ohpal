"""Captured console log + a window to view it.

``LogBus`` collects text (the app's own status/error lines, and — when the tee
is installed in app.py — everything written to stdout/stderr, including ohpal's
prints). Writes can come from worker threads, so appends are locked and delivery
to the UI goes through a queued Qt signal. ``LogWindow`` is a separate, non-modal
window that shows the history and live output.
"""

from __future__ import annotations

import threading
from collections import deque

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class LogBus(QObject):
    """Thread-safe sink for log text with a bounded history."""

    message = pyqtSignal(str)

    def __init__(self, max_lines: int = 5000) -> None:
        super().__init__()
        self._lines: deque[str] = deque(maxlen=max_lines)
        self._lock = threading.Lock()

    def write_text(self, text: str) -> None:
        if not text:
            return
        with self._lock:
            self._lines.append(text)
        self.message.emit(text)

    def log_line(self, text: str) -> None:
        self.write_text(text if text.endswith("\n") else text + "\n")

    def history(self) -> str:
        with self._lock:
            return "".join(self._lines)

    def clear(self) -> None:
        with self._lock:
            self._lines.clear()


class StreamTee:
    """Writes to the original stream *and* the bus (for sys.stdout/stderr)."""

    def __init__(self, bus: LogBus, original) -> None:
        self._bus = bus
        self._orig = original

    def write(self, s: str) -> int:
        try:
            if self._orig is not None:
                self._orig.write(s)
        except Exception:  # noqa: BLE001 - never let logging crash the app
            pass
        self._bus.write_text(s)
        return len(s)

    def flush(self) -> None:
        try:
            if self._orig is not None:
                self._orig.flush()
        except Exception:  # noqa: BLE001
            pass


class LogWindow(QMainWindow):
    """A separate window showing the captured console output."""

    def __init__(self, bus: LogBus, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Log")
        self.resize(760, 420)
        self._bus = bus

        body = QWidget()
        lay = QVBoxLayout(body)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setFont(QFont("monospace", 10))
        self.view.setMaximumBlockCount(10000)
        self.view.setPlainText(bus.history())
        self._scroll_to_end()
        lay.addWidget(self.view)

        row = QHBoxLayout()
        row.addStretch(1)
        clear = QPushButton("Clear")
        clear.clicked.connect(self._clear)
        row.addWidget(clear)
        lay.addLayout(row)

        self.setCentralWidget(body)
        bus.message.connect(self._append)

    def _append(self, text: str) -> None:
        self.view.moveCursor(self.view.textCursor().MoveOperation.End)
        self.view.insertPlainText(text)
        self._scroll_to_end()

    def _scroll_to_end(self) -> None:
        sb = self.view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _clear(self) -> None:
        self._bus.clear()
        self.view.clear()
