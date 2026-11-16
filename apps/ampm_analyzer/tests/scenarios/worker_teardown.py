"""Workers are destroyed on the main thread (never their own: PyQt deadlock),
and none leak; plot toolbars rebuild as queries finish without freezing."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import gc, os, sys, tempfile, threading, time
BUILD = sys.argv[1]
from PyQt6.QtCore import QEventLoop, QTimer, Qt
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from ampm_analyzer.shell import controller as cmod, plot_window as pwmod, workers
from ampm_analyzer.shell.plotspec import PlotSpec, default_spec
from ampm_analyzer.shell.window import MainWindow
main = threading.get_ident(); made, gone, spies = [], [], []
orig = workers.release_after
def watched(thread, worker):
    made.append(type(worker).__name__)
    import weakref
    from PyQt6.QtTest import QSignalSpy
    weakref.finalize(worker, lambda: gone.append(threading.get_ident()))  # where it is freed
    spies.append(QSignalSpy(worker.destroyed))                            # C++ really deleted
    orig(thread, worker)
cmod.release_after = pwmod.release_after = watched
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
            for _ in range(40): app.processEvents(); time.sleep(0.005)
            if not c._queue and c._current is None: return
        time.sleep(0.02)
wait_ready(lambda: c.open_recent(BUILD)); drain()
cols = list(s.result.df.columns); MP = next(n for n in cols if "elt" in n and "ool" in n)
t0 = time.time()
for i in range(3):   # each finishing query re-renders and rebuilds the toolbar
    for spec in (PlotSpec(kind="KDE", x=MP, y="density", group_by="part_id"),
                 PlotSpec(kind="2D Scatter", x="Demand X", y="Demand Y", color="part_id"),
                 default_spec("Histogram", cols, s.renames)):
        w._open_plot(spec, ("all", None, None))
    drain()
lv = w._open_plot(default_spec("Layer Viewer", cols, s.renames), ("single", s.store.layers[0], s.store.layers[0])); drain()
for _ in range(6):
    lv.set_control("layer_next"); time.sleep(0.12); drain()
w._popout_plot(); drain(); win = w._detached[-1]
win._tab.set_control("layer_prev"); time.sleep(0.12)
for _ in range(100): app.processEvents(); time.sleep(0.01)
for _ in range(20): gc.collect(); app.processEvents(); time.sleep(0.02)
print(f"{len(made)} workers ({sorted(set(made))}) in {time.time() - t0:.0f}s; destroyed {len(gone)}")
assert len(made) >= 12, made
assert gone and all(t == main for t in gone), "a worker was destroyed off the main thread"
assert len(gone) >= len(made) - 1, (len(made), len(gone))   # at most the newest still held
assert len(workers._RETIRING) <= 1, workers._RETIRING
deleted = sum(len(x) for x in spies)
print("C++ workers deleted:", deleted)
assert deleted >= len(made) - 1, (deleted, len(made))
c.shutdown()
print("TEARDOWN CHECKS PASS")
