"""DBSCAN for any purpose (the Data toolbar's DBSCAN clusters): cluster the
rows the filters keep, in every built layer, on the position and / or other
columns, in the background; the result is a column ("1" the largest cluster,
... "noise"; rows left out get none) joined on (layer, Start time), so it
follows layer changes, plots and renames. One undo step; recorded in a macro,
whose run clusters again (and waits for it)."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import os, sys, tempfile, time
BUILD = sys.argv[1]
TMP = tempfile.mkdtemp()
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog
app = QApplication([])
from ampm_viewer.shell import cluster_dialog, controller as cmod, macro_dialog, macros
from ampm_viewer.shell.cluster_dialog import ClusterDialog, check_settings
from ampm_viewer.shell.plotspec import PlotSpec
from ampm_viewer.shell.window import MainWindow

told = []
cmod._tell = lambda *a, **k: told.append(a[1:])
w = MainWindow(); w.resize(1300, 800); w.show()
A, c, s, R = w.actions, w.controller, w.session, w.recorder
def pump(n=20):
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
def wait_cluster(limit=300):
    t0 = time.time()
    while c.cluster_running() and time.time() - t0 < limit:
        app.processEvents(); time.sleep(0.02)
    drain()

wait_ready(lambda: c.open_recent(BUILD)); drain()
dt = w._data_tab
MP = next(n for n in dt._columns if "elt" in n and "ool" in n)

# -- the button and the dialog ---------------------------------------------
acts = [a for a in w.toolbar.actions() if a.text() == "DBSCAN clusters"]
assert len(acts) == 1 and acts[0].isEnabled(), "the Data toolbar's DBSCAN button"
inputs = w._cluster_dialog_inputs()
assert MP in inputs["columns"] and inputs["position"] == ["Demand X", "Demand Y", "Z"]
assert inputs["defaults"] == c.dbscan_params()
assert inputs["suggest"](MP) > 0
dlg = ClusterDialog(parent=w, **inputs)
assert dlg.settings()["name"] == "cluster" and dlg.settings()["position"]
assert dlg.settings()["features"] == [], "starts on the position alone"
per_chunk, overlap = c.dbscan_chunking()
assert dlg.settings()["layers_per_chunk"] == per_chunk
assert dlg.settings()["overlap_layers"] == overlap      # None: Auto
th = c.layer_thickness()
def problem(**kw):
    return check_settings(dict(dlg.settings(), **kw), inputs["columns"],
                          inputs["position"], set(), layer_thickness=th)
assert "overlap layers" in problem(overlap_layers=1)
assert "more than the overlap" in problem(layers_per_chunk=2)
assert problem(layers_per_chunk=20, overlap_layers=8) == ""
assert check_settings(dict(dlg.settings(), position=False), inputs["columns"],
                      inputs["position"], set()) == \
    "Cluster on the position, other columns, or both."
dlg.add_column(MP); dlg.add_column("Demand X")
assert "already" in check_settings(dlg.settings(), inputs["columns"],
                                   inputs["position"], set())
dlg._remove_row(dlg._rows[1])
assert dlg.settings()["features"] == [[MP, inputs["suggest"](MP)]]
print("button and dialog: position + columns, checks")

# -- run it in the background on the filtered rows ------------------------
w._run("filter_add", condition=f"[{MP}] > 400"); drain()
kept = s.result.df.height
settings = {"name": "hot spots", "position": True, "eps_xy": 0.5, "eps_z": 0.09,
            "features": [[MP, 50.0]], "min_samples": 10,
            "layers_per_chunk": 15, "overlap_layers": None}
ClusterDialog.exec = lambda self: QDialog.DialogCode.Accepted
ClusterDialog.settings = lambda self: dict(settings)
w._add_cluster_column()
assert c.cluster_running() and w._job_label.isVisible(), "runs in the background"
assert "DBSCAN 'hot spots'" in w._job_label.text()
wait_cluster()
assert not c.cluster_running() and not w._job_label.isVisible()
col = s.result.df["hot spots"]
assert str(col.dtype).startswith("Enum") and col.null_count() == 0 and s.result.df.height == kept
vals = set(col.unique().to_list())
assert "noise" in vals and "1" in vals, vals
d = next(x for x in s.derivations if x["name"] == "hot spots")
assert d["kind"] == "cluster" and os.path.isfile(d["file"])
assert d["settings"]["layers_per_chunk"] == 15
assert d["info"]["n_points"] >= kept and d["info"]["n_clusters"] >= 1
log = w.log_bus.history()
assert "DBSCAN 'hot spots':" in log and "clusters in" in log and "noise" in log
# The status bar's progress is in the log too (without the trailing dots), not twice in a row.
steps = [l for l in log.splitlines() if l.startswith("DBSCAN 'hot spots': ") and "clusters in" not in l]
assert "DBSCAN 'hot spots': starting" in steps and any("clustering" in l for l in steps), steps
assert not any(l.endswith("\u2026") for l in steps) and all(a != b for a, b in zip(steps, steps[1:])), steps
# Loading a layer is for the status bar, not the log.
assert "Loading layer" not in log and "Loaded layer" not in log, [l for l in log.splitlines() if "oad" in l]
print("ran in the background:", d["info"]["n_clusters"], "clusters,",
      d["info"]["n_noise"], "noise of", d["info"]["n_points"])

# Rows the filter left out get no cluster; the column follows the layer.
w._run("filter_reset"); drain()
col = s.result.df["hot spots"]
assert col.null_count() > 0 and col.null_count() < s.result.df.height
layers = c.available_layers()
wait_ready(lambda: w._on_layer_changed(layers[2])); drain()
assert "hot spots" in s.result.df.columns
# Renaming the keys and the column keeps it working.
w._run("rename", old="Start time", new="Start (us)"); drain()
w._run("rename", old="hot spots", new="hot"); drain()
assert s.result.df["hot"].null_count() < s.result.df.height
print("joined on layer and Start time: nulls where filtered, follows layers and renames")

# A plot coloured by it.
tab = w._open_plot(PlotSpec(kind="2D Scatter", x="Demand X", y="Demand Y", color="hot"),
                   ("all", None, None)); drain()
assert tab._df is not None and "hot" in tab._df.columns and tab._df["hot"].null_count() < tab._df.height
print("a plot coloured by the clusters")

# -- one undo step ----------------------------------------------------------
w._run("rename", old="hot", new="hot spots"); drain()
w._run("rename", old="Start (us)", new="Start time"); drain()
w._undo(); w._undo(); drain()        # the two renames back
w._undo(); drain()                   # rename hot spots -> hot (the earlier one)
w._undo(); drain()                   # rename Start time
w._undo(); drain()                   # filter reset
w._undo(); drain()                   # the DBSCAN column
assert not any(x["kind"] == "cluster" for x in s.derivations if x.get("kind")), s.derivations
w._redo(); drain()
assert any(x.get("kind") == "cluster" for x in s.derivations)
print("one undo step (and redo)")

# -- cancel ------------------------------------------------------------------
settings = dict(settings, name="later")
w._add_cluster_column()
assert c.cluster_running()
c.cancel_cluster(ask=False); wait_cluster()
assert "later" not in [x["name"] for x in s.derivations]
assert "cancelled" in w.log_bus.history().splitlines()[-1]
print("Cancel stops it: no column")

# -- a macro: recorded, and its run clusters again, waiting for it ---------
mfile = os.path.join(TMP, "clusters.macro.json")
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (mfile, ""))
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (mfile, ""))
macro_dialog.MacroPreviewDialog.exec = lambda self: QDialog.DialogCode.Accepted
macro_dialog.MacroSaveDialog.exec = lambda self: QDialog.DialogCode.Accepted
w._toggle_macro_recording()
settings = {"name": "by value", "position": False, "eps_xy": 0.3, "eps_z": 0.06,
            "features": [[MP, 20.0]], "min_samples": 25,
            "layers_per_chunk": 11, "overlap_layers": None}
w._add_cluster_column(); wait_cluster()
assert "by value" in s.result.df.columns
w._toggle_macro_recording()
name, steps = macros.load(mfile)
step = next(st for st in steps if st["op"] == "cluster")
assert "labels" not in step["params"] and step["params"]["features"] == [[MP, 20.0]]
assert "DBSCAN clusters" in macros.describe("cluster", step["params"])
w._run("remove", names=["by value"]); drain()
assert "by value" not in s.result.df.columns
shown = []
real_exec = cluster_dialog.ClusterRunDialog.exec
def run_exec(self):
    shown.append(self.status.text()); return real_exec(self)
cluster_dialog.ClusterRunDialog.exec = run_exec
w._run_macro(mfile); drain()
assert shown, "the run waited for the clustering, with its progress window"
assert "by value" in s.result.df.columns
assert str(s.result.df["by value"].dtype).startswith("Enum")
print("macro: recorded without the result file; its run clusters again")
assert not told, told
print("ALL OK")
c.shutdown()
