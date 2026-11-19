"""File ▸ Close: closes the build and every plot (tabs and floating windows),
as if the app were closed and started again. A fresh window takes the old
one's place (MainWindow.relaunch); the old one closes as at app exit, so the
build's plots and settings are saved and come back when it is reopened. It
asks first only when something would be lost (a running DBSCAN, a macro being
recorded). With nothing open, Close just goes back to the landing page."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import sys, time
BUILD = sys.argv[1]
from PyQt6 import sip
from PyQt6.QtCore import QEvent, QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from ampm_viewer.shell import controller as cmod, message_dialog
from ampm_viewer.shell.backstage import LIBRARY, START
from ampm_viewer.shell.plotspec import PlotSpec, default_spec
from ampm_viewer.shell.window import APP_TITLE, MainWindow

cmod._tell = lambda *a, **k: None
asked = []
answer = [True]
def fake_ask(parent, title, text, **k):
    asked.append((title, text)); return answer[0]
message_dialog.ask = fake_ask

def pump(n=20):
    for _ in range(n):
        app.processEvents(); time.sleep(0.005)
    # deleteLater runs when control is back in an event loop; a test has none.
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
def drain(w):
    c = w.controller; t0 = time.time()
    while time.time() - t0 < 300:
        app.processEvents()
        if not c._queue and c._current is None and not c._busy:
            pump()
            if not c._queue and c._current is None and not c._busy: return
        time.sleep(0.01)
def open_build(w):
    s = w.session
    loop = QEventLoop(); h = s.queryReady.connect(lambda *_: loop.quit())
    QTimer.singleShot(240000, loop.quit); w.controller.open_recent(BUILD); loop.exec()
    s.queryReady.disconnect(h); drain(w)
def close(w):
    """Press File ▸ Close; the window now in charge (a new one if relaunched)."""
    got = []
    w.relaunched.connect(got.append)
    w.tabbar.setCurrentIndex(0); pump()
    assert w.backstage.btn_close.isVisible(), "Close shows while there's something to close"
    w.backstage.btn_close.click(); pump(40)
    return got[0] if got else w

w = MainWindow(); w.resize(1200, 760); w.show()
open_build(w)
cols = list(w.session.result.df.columns)
MP = next(n for n in cols if "elt" in n and "ool" in n)
w._run("filter_add", condition=f"[{MP}] > 100"); drain(w)
w._open_plot(PlotSpec(kind="2D Scatter", x="Demand X", y="Demand Y", color=MP), ("all", None, None)); drain(w)
w._open_plot(default_spec("Histogram", cols, w.session.renames, dbscan=w.controller.dbscan_params()),
             ("all", None, None)); drain(w)
w._popout_plot(); pump(40)                     # the histogram, as a floating window
assert len(w._plot_tabs) == 1 and len(w._detached) == 1
floating = w._detached[0]
old = w
geometry, name = old.geometry(), old.session.build_name
gone = lambda obj: sip.isdeleted(obj) or not obj.isVisible()

# -- Close: a new window, as the app starts --------------------------------
w = close(old)
assert w is not old and not asked, "nothing would be lost: no question"
assert gone(old) and gone(floating), "old window and floating plots closed"
assert w.isVisible() and w.geometry() == geometry
assert w.session.store is None and w._plot_tabs == [] and w._detached == [] and w._data_tab is None
assert w.windowTitle() == APP_TITLE and w.tabbar.count() == 1, w.tabbar.count()
assert w.backstage.main_stack.currentIndex() == START and not w.backstage.btn_close.isVisible()
assert not w.backstage.btn_datastore.isVisible() and not w.backstage.btn_info.isVisible()
assert w._log.text() == f"Closed {name}.", w._log.text()
t0 = time.time()
while not sip.isdeleted(old) and time.time() - t0 < 20: pump(5)
assert sip.isdeleted(old), "the old window is deleted once its work has stopped"
print("Close: a fresh window in place; build, plot tab and floating plot gone; old window deleted")

# Reopening the build brings back what it had: its filter, and both plots
# (the floating one as a tab).
open_build(w)
assert w.controller.filters() == [f"[{MP}] > 100"], w.controller.filters()
t0 = time.time()
while len(w._plot_tabs) < 2 and time.time() - t0 < 60: pump(5)
drain(w)
assert sorted(t.spec.kind for t in w._plot_tabs) == ["2D Scatter", "Histogram"], [t.spec.kind for t in w._plot_tabs]
print("reopened: its filter and both plots are back")

# -- Something would be lost: asked first; Cancel keeps everything ------------
from ampm_viewer.shell import cluster_dialog
started = w.controller.start_cluster(
    {"name": "c", "position": False, "eps_xy": 0.3, "eps_z": 0.06,
     "features": [[MP, 20.0]], "min_samples": 25},
    on_done=lambda *a: None, on_error=lambda *a: None)
assert started is None and w.controller.cluster_running()
w._toggle_macro_recording()
answer[0] = False
same = close(w)
assert same is w and w.isVisible() and w.session.store is not None and w.controller.cluster_running()
title, text = asked[-1]
assert title == "Close everything?" and "DBSCAN clusters is stopped" in text and "macro being recorded is discarded" in text, text
print("asked first (DBSCAN running, macro recording); Cancel kept everything")
answer[0] = True
old = w
w = close(old)
assert w is not old and w.session.store is None and not w.recorder.active
t0 = time.time()
while not sip.isdeleted(old) and time.time() - t0 < 30: pump(5)
assert sip.isdeleted(old), "deleted once the stopped DBSCAN's thread ended"
print("Close: DBSCAN stopped, recording dropped, fresh window")

# -- Nothing open: Close is only "back to the landing page" -------------------
w.tabbar.setCurrentIndex(0); w.backstage.main_stack.setCurrentIndex(LIBRARY); pump()
assert w.backstage.btn_close.isVisible()
same = close(w)
assert same is w and w.backstage.main_stack.currentIndex() == START and not w.backstage.btn_close.isVisible()
print("nothing open: Close goes back to the landing page")
print("ALL OK")
w.controller.shutdown()
