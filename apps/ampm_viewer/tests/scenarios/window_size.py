"""The main window never resizes itself. Opening a plot (and the side panel
it brings), the File tab or a wider page used to raise the window's minimum to
what its contents asked for, and Qt then enlarged the window to it: off the
screen of a maximised or full-screen window. Only the user sizes it now; the
contents fit what they are given."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import sys, time
BUILD = sys.argv[1]
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from ampm_viewer.shell import controller as cmod
from ampm_viewer.shell.plotspec import PLOT_KINDS, default_spec
from ampm_viewer.shell.window import MIN_WINDOW_SIZE, MainWindow

cmod._tell = lambda *a, **k: None
w = MainWindow(); c, s = w.controller, w.session
SIZE = (900, 600)
w.resize(*SIZE); w.show()
def pump(n=30):
    for _ in range(n): app.processEvents(); time.sleep(0.002)
def drain():
    t0 = time.time()
    while time.time() - t0 < 300:
        app.processEvents()
        if not c._queue and c._current is None and not c._busy:
            pump()
            if not c._queue and c._current is None and not c._busy: return
        time.sleep(0.01)
def wait_ready(kick):
    loop = QEventLoop(); h = s.queryReady.connect(lambda *_: loop.quit())
    QTimer.singleShot(240000, loop.quit); kick(); loop.exec(); s.queryReady.disconnect(h)
def same_size(what):
    pump()
    assert (w.width(), w.height()) == SIZE, f"{what}: {w.width()}x{w.height()}"

assert w.minimumSize() == MIN_WINDOW_SIZE, "an explicit minimum, not the contents'"
same_size("start")
wait_ready(lambda: c.open_recent(BUILD)); drain(); same_size("build open")
w._toggle_sidebar(True); same_size("data tab + side panel")
w.tabbar.setCurrentIndex(0); same_size("File tab")
cols = list(s.result.df.columns)
layers = c.available_layers()
for kind in PLOT_KINDS:
    span = (("single", layers[0], layers[0]) if kind in ("Layer Viewer", "Single Layer")
            else ("all", None, None))
    tab = w._open_plot(default_spec(kind, cols, s.renames, dbscan=c.dbscan_params()), span)
    drain(); same_size(f"plot {kind}")
    w._toggle_sidebar(True); same_size(f"plot {kind} + side panel")
print(f"window stays {SIZE[0]}x{SIZE[1]} through every plot kind and the side panel")

# The pages ask only for the room of the one showing.
w.resize(MIN_WINDOW_SIZE); pump()
assert (w.width(), w.height()) == (MIN_WINDOW_SIZE.width(), MIN_WINDOW_SIZE.height())
for i in range(w.tabbar.count()):
    w.tabbar.setCurrentIndex(i); pump()
    assert w.width() == MIN_WINDOW_SIZE.width(), (i, w.width())
    assert w.stack.minimumSizeHint().width() <= w.width(), (i, w.stack.minimumSizeHint())
print(f"every tab fits the smallest window, {MIN_WINDOW_SIZE.width()}x{MIN_WINDOW_SIZE.height()}")
print("ALL OK")
c.shutdown()
