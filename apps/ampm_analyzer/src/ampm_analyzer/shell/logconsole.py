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

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizeGrip,
    QVBoxLayout,
    QWidget,
)

from .card import DraggableCard


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


class LogWindow(DraggableCard, QWidget):
    """A frameless-card window showing the captured console output.

    Matches the app's other popups: no native title bar (drag any inert part
    to move it), a rounded card, and a corner grip to resize."""

    def __init__(self, bus: LogBus, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Log")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(420, 240)
        self.resize(760, 420)
        self._bus = bus

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("LogCard")
        card.setStyleSheet(
            "#LogCard { background: palette(window); "
            "border: 1px solid palette(mid); border-radius: 10px; }"
        )
        outer.addWidget(card)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        title = QLabel("Log")
        title.setStyleSheet("font-size: 14pt; font-weight: 600;")
        lay.addWidget(title)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setFrameShape(QFrame.Shape.NoFrame)
        self.view.setFont(QFont("monospace", 10))
        self.view.setMaximumBlockCount(10000)
        self.view.setPlainText(bus.history())
        self._scroll_to_end()
        lay.addWidget(self.view, 1)

        row = QHBoxLayout()
        export = QPushButton("Export log")
        export.clicked.connect(self._export)
        row.addWidget(export)
        clear = QPushButton("Clear")
        clear.clicked.connect(self._clear)
        row.addWidget(clear)
        row.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        row.addWidget(close)
        # A corner grip to resize the frameless window.
        row.addWidget(QSizeGrip(self), 0,
                      Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        lay.addLayout(row)

        bus.message.connect(self._append)

    def _append(self, text: str) -> None:
        self.view.moveCursor(self.view.textCursor().MoveOperation.End)
        self.view.insertPlainText(text)
        self._scroll_to_end()

    def _scroll_to_end(self) -> None:
        sb = self.view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _export(self) -> None:
        from datetime import datetime
        from pathlib import Path

        start = str(Path.home() / f"ampm-log-{datetime.now():%Y%m%d-%H%M%S}.txt")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export log", start, "Text files (*.txt *.log);;All files (*)")
        if not path:
            return
        try:
            Path(path).write_text(self._bus.history(), encoding="utf-8")
        except OSError as exc:
            from .message_dialog import tell
            tell(self, "Export log", f"Couldn't save the log:\n{exc}")

    def _clear(self) -> None:
        self._bus.clear()
        self.view.clear()
