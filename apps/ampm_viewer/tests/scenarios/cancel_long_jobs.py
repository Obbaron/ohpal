"""DBSCAN settings on the setup page (kept per build); DBSCAN in a child process
with progress and Cancel; Cancel for a DataStore build; shutdown mid-DBSCAN."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import os, sys, time
BUILD = sys.argv[1]
import numpy as np, polars as pl
from pathlib import Path
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication

# --- ohpal: the chunked DBSCAN progress hook --------------------------------------
from ohpal.ampm.clustering import cluster_dbscan_chunked
rng = np.random.default_rng(0)
n = 6000
syn = pl.DataFrame({"Demand X": rng.uniform(0, 5, n), "Demand Y": rng.uniform(0, 5, n),
                    "layer": rng.integers(1, 31, n)}).with_columns((pl.col("layer") * 0.03).alias("Z"))
calls = []
a = cluster_dbscan_chunked(syn, eps_xy=0.3, eps_z=0.06, min_samples=5, layers_per_chunk=11,
                           layer_thickness=0.03, verbose=False, progress=lambda i, k: calls.append((i, k)))
b = cluster_dbscan_chunked(syn, eps_xy=0.3, eps_z=0.06, min_samples=5, layers_per_chunk=11,
                           layer_thickness=0.03, verbose=False)
assert calls and [i for i, _ in calls] == list(range(1, len(calls) + 1)) and len({k for _, k in calls}) == 1
assert a["cluster"].to_list() == b["cluster"].to_list(), "the hook doesn't change the result"
print("ohpal: progress(chunk, n) per chunk:", calls)

app = QApplication([])
from ampm_viewer.shell import controller as cmod, uistate
from ampm_viewer.shell.window import MainWindow
told, asks = [], []
cmod._tell = lambda parent, title, text, **k: told.append((title, text))
cmod._ask = lambda parent, title, text, **k: (asks.append(title), True)[1]
w = MainWindow(); w.resize(1200, 700); w.show(); c, s = w.controller, w.session
def pump(cond, limit=600):
    t0 = time.time()
    while time.time() - t0 < limit:
        app.processEvents()
        if cond(): return True
        time.sleep(0.02)
    raise SystemExit("timed out")
def idle():
    return (not c._queue and c._current is None and not c._busy and c._dbscan_thread is None
            and c._mask_thread is None)
def wait_ready(kick):
    loop = QEventLoop(); h = s.queryReady.connect(lambda *_: loop.quit())
    QTimer.singleShot(240000, loop.quit); kick(); loop.exec(); s.queryReady.disconnect(h)
wait_ready(lambda: c.open_recent(BUILD)); pump(idle)
cache = Path(s.store.cache_dir)

# --- the setup page: DBSCAN settings appear with DBSCAN, start from config.toml --------
f = w.backstage.ds_form
w.backstage.set_datastore_config(c.current_config(), list(s.store.layers), list(s.store.columns))
f.chk_mask.setChecked(False); f.chk_parts.setChecked(True); f.cmb_parts.setCurrentText("Direct"); app.processEvents()
assert f.dbscan_detail.isHidden() and f.recipe()["dbscan"] is None
f.cmb_parts.setCurrentText("DBSCAN"); app.processEvents()
assert not f.dbscan_detail.isHidden()
assert f.dbscan_values() == {"eps_xy": 0.3, "eps_z": 0.06, "min_samples": 10,
                            "layers_per_chunk": 11, "overlap_layers": None}, f.dbscan_values()
assert f.recipe()["dbscan"] == f.dbscan_values()
print("setup page: XY radius / Z radius / Min samples with DBSCAN, from config.toml")

# --- DBSCAN runs in a child process, reports progress, can be cancelled --------------
for p in cache.glob("dbscan_part_labels*"): p.unlink()
f.spin_eps_xy.setValue(0.35); f.spin_min_samples.setValue(12)
notes = []
orig_job = w.set_background_job
def job(text, on_cancel=None):
    notes.append(text)
    orig_job(text, on_cancel)
w.set_background_job = job
wait_ready(w._on_build_requested)                       # the build lands; DBSCAN starts behind it
assert c.dbscan_params() == (0.35, 0.06, 12) and uistate.load_state(cache)["dbscan"] == {"eps_xy": 0.35, "eps_z": 0.06, "min_samples": 12, "layers_per_chunk": 11, "overlap_layers": None}
pump(lambda: any(t and "clustering chunk" in t for t in notes))
assert not w._job_cancel_btn.isHidden() and w._job_cancel is not None
proc = c._dbscan_worker._process; assert proc is not None and proc.poll() is None and proc.pid != os.getpid()
assert "ampm_viewer.dbscan_job" in " ".join(proc.args), proc.args
t0 = time.time(); w._job_cancel_btn.click()               # (the confirmation answers Stop)
pump(lambda: c._dbscan_thread is None, 30); took = time.time() - t0
assert asks[-1] == "Stop DBSCAN?" and proc.poll() is not None, (asks, proc)
assert took < 5, f"cancel took {took:.1f}s"
assert "cancelled" in w._log._full and w._job_cancel_btn.isHidden() and not w._job_label.isVisible()
assert not list(cache.glob("dbscan_part_labels*")) and not (cache / "dbscan_input.parquet").exists()
assert not (cache / "dbscan_job.json").exists() and not (cache / "dbscan_job.progress").exists()
assert not c.has_part_assignment() and not told, told
steps = [t for t in notes if t]
print(f"DBSCAN: {steps[:3]} ... {steps[-2:]}; cancelled in {took:.2f}s, process ended, nothing left behind")

# --- and runs to the end in its process, with the same settings ------------------------
notes.clear()
wait_ready(w._on_build_requested); pump(idle)
assert c.has_part_assignment() and len(c.assigned_part_ids()) == 20, told
meta = (cache / "dbscan_part_labels.json").read_text()
assert '"eps_xy": 0.35' in meta and '"min_samples": 12' in meta
assert not (cache / "dbscan_input.parquet").exists() and not (cache / "dbscan_part_labels.partial.parquet").exists()
assert any(t and "matching clusters to parts" in t for t in notes), notes
print("DBSCAN to the end in its process: 20 parts; settings recorded with the saved result")

# --- reopen: the build's own settings come back ------------------------------------
wait_ready(lambda: c.open_recent(BUILD)); pump(idle)
assert c.dbscan_params() == (0.35, 0.06, 12) and c.has_part_assignment()
w.backstage.set_datastore_config(c.current_config(), list(s.store.layers), list(s.store.columns), {})
assert f.dbscan_values() == {"eps_xy": 0.35, "eps_z": 0.06, "min_samples": 12,
                            "layers_per_chunk": 11, "overlap_layers": None}
from ampm_viewer.shell.plotspec import KDIST, default_spec
sp = default_spec(KDIST, list(s.result.df.columns), s.renames, dbscan=c.dbscan_params())
assert (sp.eps_xy, sp.k) == (0.35, 12), "the K-distance plot starts from them too"
print("reopen: settings restored on the setup page and the K-distance plot")

# --- Cancel a DataStore build ---------------------------------------------------------
f.cmb_parts.setCurrentText("Direct"); c._setup_force = True
progress = []; s.cacheProgress.connect(lambda d, t, L: progress.append(d))
w._on_build_requested()
pump(lambda: progress and not w._build_cancel_btn.isHidden())
w._build_cancel_btn.click()
pump(lambda: not c._busy and c._thread is None, 120)
for _ in range(20): app.processEvents()
assert w._build_cancel_btn.isHidden() and w.tabbar.currentIndex() == 0
assert w.backstage.main_stack.currentIndex() == 1, "back on the setup page"
assert f.cmb_parts.currentText() == "Direct", "the page's choices kept"
assert "DataStore build cancelled after" in w._log._full and "of 10 layers" in w._log._full, w._log._full
assert max(progress) < 10 and c._dbscan_thread is None
print("build cancel:", w._log._full)
wait_ready(w._on_build_requested); pump(idle)              # building again works
assert s.result is not None and not w._build_cancel_btn.isVisible()

# --- closing mid-DBSCAN ends its process at once ----------------------------------------
f.cmb_parts.setCurrentText("DBSCAN"); f.spin_min_samples.setValue(11); notes.clear()
wait_ready(w._on_build_requested)
pump(lambda: any(t and "clustering chunk" in t for t in notes))
proc = c._dbscan_worker._process
t0 = time.time(); c.shutdown(); took = time.time() - t0
assert proc.poll() is not None and took < 5, (proc, took)
print(f"shutdown mid-DBSCAN: process ended, {took:.2f}s")
print("CANCEL CHECKS PASS")
