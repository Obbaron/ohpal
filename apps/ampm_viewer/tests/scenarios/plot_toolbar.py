"""The plot toolbar has no selection group; everything else is intact."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import sys, time
BUILD = sys.argv[1]
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication, QComboBox
app = QApplication([])
from ampm_viewer.shell import controller as cmod, icons, toolbars
from ampm_viewer.shell.plotspec import PlotSpec
from ampm_viewer.shell.window import MainWindow
assert not hasattr(toolbars, "_combo")
for name in ("select", "invert_sel", "sel_box", "sel_lasso"):
    assert name not in icons.UI, name
for name in icons.UI:   # every remaining toolbar icon still resolves
    assert not icons.ui(name, "#000000").isNull(), name
cmod._tell = lambda *a, **k: None
w = MainWindow(); w.resize(1200, 760); w.show(); c, s = w.controller, w.session
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
cols = list(s.result.df.columns); MP = next(n for n in cols if "elt" in n and "ool" in n)
w._open_plot(PlotSpec(kind="2D Scatter", x="Demand X", y="Demand Y", color=MP), ("all", None, None)); drain()
tips = [a.text() for a in w.toolbar.actions() if a.text()]  # names (tooltips add shortcuts)
print("plot toolbar:", tips)
assert not any(t in tips for t in ("Clear", "Invert", "Select")), tips
assert not w.toolbar.findChildren(QComboBox), "no combo left on the plot toolbar"
assert tips[:9] == ["Show/hide panel", "Reset view", "Equal axes (1:1)", "Axes", "Grid", "Legend", "Title", "Trend line", "Screenshot"], tips
assert "BBox" not in tips, "a 2D plot has no bounding box"
assert "Pop out" in tips
win = (w._popout_plot(), app.processEvents(), w._detached[-1])[2]
ptips = [a.text() for a in win._toolbar.actions() if a.text()]
print("floating window toolbar:", ptips)
assert not any(t in ptips for t in ("Clear", "Invert", "Select")) and not win._toolbar.findChildren(QComboBox)
assert "Dock in" in ptips
# the Data toolbar has no Deselect button either: empty space deselects
w.tabbar.setCurrentIndex(w.stack.indexOf(w._data_tab)); app.processEvents()
assert "Reset selection" not in [a.text() for a in w.toolbar.actions()]
c.shutdown()
print("PLOT TOOLBAR CHECKS PASS")
