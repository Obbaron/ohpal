"""First plot must not rebuild the main window (the close-and-reopen flash)."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import os, sys, tempfile, time
BUILD = sys.argv[1]
from PyQt6.QtCore import QEvent, QEventLoop, QObject, QTimer
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from ampm_analyzer.shell import controller as cmod
from ampm_analyzer.shell.plotspec import PlotSpec
from ampm_analyzer.shell import window as wmod
if len(sys.argv) > 2 and sys.argv[2] == "unprimed":      # what the app did before
    wmod.MainWindow._prime_opengl = lambda self: None
cmod._tell = lambda *a, **k: None
class Spy(QObject):
    def __init__(self): super().__init__(); self.n = 0
    def eventFilter(self, o, e):
        if e.type() == QEvent.Type.WinIdChange: self.n += 1
        return False
w = wmod.MainWindow(); w.resize(1200, 700); spy = Spy(); w.installEventFilter(spy)
w.show(); app.processEvents(); c, s = w.controller, w.session
def wait_ready(kick):
    loop = QEventLoop(); h = s.queryReady.connect(lambda *_: loop.quit())
    QTimer.singleShot(240000, loop.quit); kick(); loop.exec(); s.queryReady.disconnect(h)
def drain():
    t0 = time.time()
    while time.time() - t0 < 300:
        app.processEvents()
        if not c._queue and c._current is None and not c._busy:
            for _ in range(30): app.processEvents()
            if not c._queue and c._current is None: return
        time.sleep(0.02)
wait_ready(lambda: c.open_recent(BUILD)); drain()
surface0, id0, n0 = w.windowHandle().surfaceType().name, int(w.winId()), spy.n
cols = list(s.result.df.columns); MP = next(n for n in cols if "elt" in n and "ool" in n)
w._open_plot(PlotSpec(kind="2D Scatter", x="Demand X", y="Demand Y", color=MP), ("all", None, None)); drain()
same1 = int(w.winId()) == id0; n1 = spy.n - n0
w._open_plot(PlotSpec(kind="Histogram", x=MP, y=MP, bins=20), ("all", None, None)); drain()
same2 = int(w.winId()) == id0
print(f"surface at start: {surface0} -> after first plot: {w.windowHandle().surfaceType().name} | "
      f"window kept on first plot: {same1} (rebuild events: {n1}) | kept on second: {same2}")
c.shutdown()
if len(sys.argv) <= 2:
    assert surface0 == "OpenGLSurface" and same1 and same2 and n1 == 0
    assert w._gl_primer is not None and w._gl_primer.isHidden() and len(w._plot_tabs) == 2
    print("GL PRIME CHECK PASSES")
