"""Files opened from outside the app (a double-clicked ``.ampmplot``) go to
the AMPM Viewer already running, rather than starting another copy.

Windows and Linux start the program again with the file on its command line:
the new process hands the file to the running one over a local socket (a
named pipe on Windows) and quits. macOS never starts a second copy: it sends
the running app a ``FileOpen`` event (handled in ``app.py``).

The running app listens with ``Listener``; ``forward`` is the new process's
side. A plain start (no file) always opens a new window, so two builds can
still be open side by side in two copies of the app. The socket's name comes
from the AMPM folder, so copies that keep their settings apart (another
``AMPM_DATA_DIR``) don't hand files to each other.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable

from PyQt6.QtCore import QObject
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

from . import settings

OPENABLE = (".ampmplot",)   # the files the app opens when given one
_TIMEOUT_MS = 1000


def server_name() -> str:
    key = str(settings.data_dir()).encode("utf-8")
    return "ampm-viewer-" + hashlib.sha1(key).hexdigest()[:12]


def openable(args) -> list[str]:
    """The arguments that are files the app opens (by their extension)."""
    return [a for a in args if str(a).lower().endswith(OPENABLE)]


def forward(paths: list[str]) -> bool:
    """Give ``paths`` to the AMPM Viewer already running. False when none is
    listening (the caller opens them itself)."""
    sock = QLocalSocket()
    sock.connectToServer(server_name())
    if not sock.waitForConnected(_TIMEOUT_MS):
        return False
    _allow_foreground()
    sock.write(json.dumps(paths).encode("utf-8") + b"\n")
    ok = sock.waitForBytesWritten(_TIMEOUT_MS)
    sock.disconnectFromServer()
    return ok


def _allow_foreground() -> None:
    """Windows only lets the foreground process bring a window to the front:
    let the running app raise its window for the file we hand it."""
    import sys

    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
    except Exception:  # noqa: BLE001 - only means the window may not come forward
        pass


class Listener(QObject):
    """Receives the files a later start hands over; calls ``on_files`` with
    them. ``listening`` is False when another copy already listens."""

    def __init__(self, on_files: Callable[[list[str]], None], parent=None) -> None:
        super().__init__(parent)
        self._on_files = on_files
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        name = server_name()
        # Another copy listening keeps the name (on Linux and macOS Qt would
        # let a second listen take it over silently). Otherwise clear a
        # socket file left by a copy that crashed, then listen.
        probe = QLocalSocket()
        probe.connectToServer(name)
        if probe.waitForConnected(200):
            probe.abort()
        else:
            QLocalServer.removeServer(name)
            self._server.listen(name)
        self.listening = self._server.isListening()
        self._server.newConnection.connect(self._accept)

    def _accept(self) -> None:
        while self._server.hasPendingConnections():
            sock = self._server.nextPendingConnection()
            buf = bytearray()

            def read(sock=sock, buf=buf) -> None:
                buf.extend(bytes(sock.readAll()))
                if not buf.endswith(b"\n"):
                    return
                try:
                    paths = [str(p) for p in json.loads(buf.decode("utf-8"))]
                except (ValueError, TypeError):
                    paths = []
                buf.clear()
                sock.disconnectFromServer()
                if paths:
                    self._on_files(paths)

            sock.readyRead.connect(read)
            sock.disconnected.connect(sock.deleteLater)
            read()

    def close(self) -> None:
        self._server.close()
