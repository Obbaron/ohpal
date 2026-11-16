"""Shutdown guard, plots closed on rebuild, LaserVIEW required, recent macros,
DBSCAN part assignment, on the real build."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import os, sys, tempfile, time
BUILD, TMP = sys.argv[1], tempfile.mkdtemp()
from PyQt6 import sip
from PyQt6.QtCore import QEventLoop, QObject, QTimer
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog, QToolButton
app = QApplication([])
import polars as pl
from ampm_analyzer.shell import controller as cmod, macro_dialog, macros, uistate
from ampm_analyzer.shell.datastore_settings import REQUIRED_COLUMNS, DataStoreSettings
from ampm_analyzer.shell.plotspec import PlotSpec
from ampm_analyzer.shell.window import MainWindow
LV = "LaserVIEW (mean)"
told = []
cmod._tell = lambda parent, title, text, **k: told.append((title, text))
w = MainWindow(); w.resize(1200, 700); w.show(); c, s = w.controller, w.session
def wait_ready(kick):
    loop = QEventLoop(); h = s.queryReady.connect(lambda *_: loop.quit())
    QTimer.singleShot(240000, loop.quit); kick(); loop.exec(); s.queryReady.disconnect(h)
def drain(limit=600):
    t0 = time.time()
    while time.time() - t0 < limit:
        app.processEvents()
        if not c._queue and c._current is None and not c._busy and c._dbscan_thread is None and c._mask_thread is None:
            for _ in range(40): app.processEvents()
            if not c._queue and c._current is None and c._dbscan_thread is None: return
        time.sleep(0.02)
    raise SystemExit("never went idle")

# old-style saved state: a column selection made before LaserVIEW was required
from ohpal.ampm.config import load_config
cache = os.path.join(load_config(BUILD)["SOURCE"], ".cache")
uistate.set_load_columns(cache, ["Demand X", "Demand Y", "Start time", "layer", "Z", "MeltVIEW melt pool (mean)"])
wait_ready(lambda: c.open_recent(BUILD)); drain()
dt = w._data_tab

# --- LaserVIEW (mean) is a required column -----------------------------------
assert LV in REQUIRED_COLUMNS and LV in dt._columns, "required column should load even for an older build"
out = w._run("remove", names=[LV]); assert not out.ok and "required" in out.message
form = DataStoreSettings()
cols = list(s.store.columns)
form.set_config({"SOURCE": "/x", "PARTS_CSV": "/p.csv", "METHOD": "dbscan"}, [1, 2, 3], cols)
rows = {r.name: r for r in form._col_rows}; names = [r.name for r in form._col_rows]
assert rows[LV].locked and rows[LV].included() and LV in form.columns()
first_locked = min(i for i, r in enumerate(form._col_rows) if r.locked)
assert all(r.locked for r in form._col_rows[first_locked:]) and names.index(LV) >= first_locked, "required columns sit together at the bottom"
assert form.chk_correction.isEnabled(), "Correction is available with the default columns now"
print("LaserVIEW required: locked, grouped at the bottom, loads on old builds; Correction available")

# --- DBSCAN is never the default, and warns when picked -----------------------
form.show(); app.processEvents()
assert form.cmb_parts.currentText() == "Direct", form.cmb_parts.currentText()
assert not form.lbl_dbscan_warn.isVisible()
form.cmb_parts.setCurrentText("DBSCAN"); app.processEvents()
assert form.lbl_dbscan_warn.isVisible() and "expensive" in form.lbl_dbscan_warn.text()
assert form.recipe()["part_method"] == "dbscan"
form.chk_parts.setChecked(False); app.processEvents(); assert not form.lbl_dbscan_warn.isVisible()
form.set_config({"SOURCE": "/x", "PARTS_CSV": "/p.csv", "METHOD": "dbscan"}, [1, 2, 3], cols, {})   # a live DBSCAN build
assert form.cmb_parts.currentText() == "DBSCAN"
print("DBSCAN: not preselected on a fresh setup; warning shown when chosen")

# --- rebuild closes live plots; rebuild WITH DBSCAN ---------------------------
w._open_plot(PlotSpec(kind="2D Scatter", x="Demand X", y="Demand Y"), ("all", None, None)); drain()
assert len(w._plot_tabs) == 1
f = w.backstage.ds_form; f.chk_mask.setChecked(False)
f.cmb_parts.setCurrentText("DBSCAN"); assert f.recipe()["part_method"] == "dbscan"
seen = []
orig_job = w.set_background_job
w.set_background_job = lambda text, on_cancel=None: (seen.append(text), orig_job(text, on_cancel))[1]
wait_ready(w._on_build_requested)
assert not w._plot_tabs, "old plots should close on a rebuild"
drain()
assert any(t and "DBSCAN" in t for t in seen) and seen[-1] is None and not w._job_label.isVisible(), seen
assert not told, told
df = s.result.df
assert "part_id" in df.columns and df["part_id"].null_count() == 0 and c.has_part_assignment()
n_parts = len(c.assigned_part_ids()); assert n_parts == 20, n_parts
assert "DBSCAN assigned 20 parts" in w._log._full, w._log._full
out = w._run("part_calc", signal="MeltVIEW melt pool (mean)", reducer="mean", name="pm"); assert out.ok, out
out = w._run("laser_params"); assert "Matched 20 of 20 parts" in out.message, out.message
print("DBSCAN build:", w._log._full if "DBSCAN" in w._log._full else "", "| per-part calc + laser params OK")

# reopen: the saved result is read back, no re-clustering
t0 = time.time(); wait_ready(lambda: c.open_recent(BUILD)); drain(); took = time.time() - t0
assert "part_id" in s.result.df.columns and "saved result" in w._log._full, w._log._full
print(f"reopen: part ids back from the saved result ({took:.1f}s incl. load)")

# clustering that finds nothing → clear popup, no part column, app carries on
f = w.backstage.ds_form; f.chk_mask.setChecked(False); f.cmb_parts.setCurrentText("DBSCAN")
f.spin_min_samples.setValue(10000)        # the setup page's settings drive DBSCAN
told.clear(); wait_ready(w._on_build_requested); drain()
assert told and told[-1][0] == "DBSCAN part assignment failed" and "Try other settings" in told[-1][1], told
assert "part_id" not in s.result.df.columns and not c.has_part_assignment()
print("DBSCAN failure:", told[-1][1][:70], "…")
assert c.dbscan_params()[2] == 10000 and uistate.load_state(cache)["dbscan"]["min_samples"] == 10000
f = w.backstage.ds_form; f.chk_mask.setChecked(False); f.cmb_parts.setCurrentText("Direct")
wait_ready(w._on_build_requested); drain(); assert c.has_part_assignment()

# --- recent macros --------------------------------------------------------------
files = {"save": [], "open": []}
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (files["save"].pop(0), ""))
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (files["open"].pop(0), ""))
macro_dialog.MacroPreviewDialog.exec = lambda self: QDialog.DialogCode.Accepted
macro_dialog.MacroSaveDialog.exec = lambda self: QDialog.DialogCode.Accepted  # Stop: nothing asked when run
macro_dialog.MacroIssuesDialog.exec = lambda self: QDialog.DialogCode.Accepted
def run_button():
    for b in w.toolbar.findChildren(QToolButton):
        if b.toolTip() == "Run a macro" and b.menu() is not None: return b
    return None
assert macros.recent() == [] and run_button() is None
for name in ("alpha", "beta"):
    w._toggle_macro_recording(); w._run("derive", name=f"m_{name}", expr="[layer] * 2")
    files["save"] = [os.path.join(TMP, name)]; w._toggle_macro_recording(); w._undo()
for _ in range(20): app.processEvents()
assert [macros.macro_name(p) for p in macros.recent()] == ["beta", "alpha"], macros.recent()
btn = run_button(); assert btn is not None
labels = [a.text() for a in btn.menu().actions() if not a.isSeparator()]
assert labels == ["beta", "alpha", "Browse…", "Open macro folder"], labels
next(a for a in btn.menu().actions() if a.text() == "alpha").trigger()   # straight from the list, no file dialog
for _ in range(30): app.processEvents()
assert any(d["name"] == "m_alpha" for d in s.derivations) and not files["open"]
assert [macros.macro_name(p) for p in macros.recent()] == ["alpha", "beta"]
os.remove(os.path.join(TMP, "beta.macro.json")); assert [macros.macro_name(p) for p in macros.recent()] == ["alpha"]
for i in range(12): macros.remember(macros.save(os.path.join(TMP, f"n{i}"), f"n{i}", [{"op": "filter_reset", "params": {}}]))
assert len(macros.recent()) == 8
w._toggle_macro_recording(); for_ = [app.processEvents() for _ in range(10)]
assert run_button() is None, "no running a macro while recording"
w.recorder.cancel()
print("recent macros: newest first, run from the list, missing files dropped, capped at 8")

# --- shutdown survives an already-deleted worker / thread ------------------------
dead = QObject(); dead.cancel = lambda: None; sip.delete(dead)
c._worker = dead; c._thread = dead; c._mask_thread = dead; c._side_thread = dead; c._dbscan_thread = dead
c.shutdown()
print("shutdown with deleted worker objects: no error")
print("ALL BATCH CHECKS PASS")
