"""LaserVIEW (mean) is always loaded (the melt-pool correction needs it) but
starts hidden in the grid: on a fresh layout, and when it first appears in a
saved layout that didn't have it. Shown once, it stays shown."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import os, sys, time
BUILD = sys.argv[1]
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from ampm_viewer.shell import controller as cmod
from ampm_viewer.shell.data_tab import DEFAULT_HIDDEN
from ampm_viewer.shell.window import MainWindow
cmod._tell = lambda *a, **k: None
w = MainWindow(); w.resize(1200, 760); w.show(); c, s = w.controller, w.session
def drain():
    t0 = time.time()
    while time.time() - t0 < 300:
        app.processEvents()
        if not c._queue and c._current is None and not c._busy:
            for _ in range(20): app.processEvents(); time.sleep(0.002)
            if not c._queue and c._current is None and not c._busy: return
        time.sleep(0.01)
loop = QEventLoop(); s.queryReady.connect(lambda *_: loop.quit())
QTimer.singleShot(240000, loop.quit); c.open_recent(BUILD); loop.exec(); drain()
dt = w._data_tab
LV = next(n for n in dt._columns if n.startswith("LaserVIEW (mean)") or n == "LaserVIEW (mean)")
assert "LaserVIEW (mean)" in DEFAULT_HIDDEN
assert LV in dt.hidden_columns(), ("hidden on a fresh layout", dt.hidden_columns())

# Shown by the user, it stays shown when the columns change.
w._run("set_visible", name=LV, visible=True); drain()
w._run("derive", name="twice", expr="[Z] * 2"); drain()
assert LV not in dt.hidden_columns() and "twice" not in dt.hidden_columns()

# A saved layout from before it was imported: it arrives hidden; the rest as saved.
others = [n for n in dt._columns if n != LV and n != "twice"]
dt.set_persisted_state(None, columns=others, order=others, hidden=[])
dt.set_dataframe(s.result.df); drain()
assert LV in dt.hidden_columns(), dt.hidden_columns()
assert "Start time" not in dt.hidden_columns(), "the saved layout's choices are kept"
print("LaserVIEW starts hidden; shown, it stays shown")
c.shutdown()
os._exit(0)
