"""Stage-4 checks on a real build: plots and Excel exports are recorded as macro
steps and replayed; exports write the data as it stood at their step."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import json, os, sys, tempfile, time
BUILD, TMP = sys.argv[1], tempfile.mkdtemp()
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog
app = QApplication([])
from openpyxl import load_workbook
from ampm_analyzer.shell import export_dialog, macro_dialog, macros, plot_dialog
from ampm_analyzer.shell.plotspec import PlotSpec
from ampm_analyzer.shell.window import MainWindow
w = MainWindow(); w.resize(1100, 700); w.show()
loop = QEventLoop(); w.session.queryReady.connect(lambda *_: loop.quit()); QTimer.singleShot(120000, loop.quit)
w.controller.open_recent(BUILD); loop.exec()
A, c, s, R = w.actions, w.controller, w.session, w.recorder
def drain(limit=180):
    t0 = time.time()
    while time.time() - t0 < limit:
        app.processEvents()
        if not c._queue and c._current is None and not c._busy:
            for _ in range(30): app.processEvents()
            if not c._queue and c._current is None: return
        time.sleep(0.02)
    raise SystemExit("queue never drained")
drain()
SRC = "MeltVIEW melt pool (mean)"; layers = list(s.store.layers); cur = s.current_layer
def state():
    snap = A.capture(); return {k: snap[k] for k in ("derivations", "removed", "renames", "filters")}
def rows(path):
    ws = load_workbook(path, read_only=True).active; return sum(1 for _ in ws.iter_rows()) - 1
def step(op, **p): return {"op": op, "params": p}

# --- dialog stubs ----------------------------------------------------------
files = {"save": [], "open": []}; popups = []
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (files["save"].pop(0), ""))
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (files["open"].pop(0), ""))
macro_dialog.MacroPreviewDialog.exec = lambda self: QDialog.DialogCode.Accepted
macro_dialog.MacroSaveDialog.exec = lambda self: QDialog.DialogCode.Accepted  # Stop: nothing asked when run
macro_dialog.MacroIssuesDialog.exec = lambda self: (popups.append(
    [self.list.item(i).text() for i in range(self.list.count())]), QDialog.DialogCode.Accepted)[1]
nxt = {}
plot_dialog.NewPlotDialog.exec = lambda self: QDialog.DialogCode.Accepted
plot_dialog.NewPlotDialog.spec = lambda self: nxt["spec"]
plot_dialog.NewPlotDialog.span = lambda self: nxt["span"]
export_dialog.ExcelExportDialog.exec = lambda self: QDialog.DialogCode.Accepted
export_dialog.ExcelExportDialog.result_values = lambda self: nxt["export"]
def new_plot(spec, span): nxt.update(spec=spec, span=span); w._new_plot(spec.kind)
def export(path, **kw):
    nxt["export"] = dict(mode="raw", columns=["Demand X", "Meltpool"], scope=("current", cur, cur),
                         respect_filters=True, path=path, sheet="Export", **kw); w._export_excel(); drain()

w._run("rename", old=SRC, new="Meltpool")       # display != original on this build
base = state(); base_plots = len(w._plot_tabs)

# --- record ----------------------------------------------------------------
w._toggle_macro_recording()
w._run("derive", name="dbl", expr="[Meltpool] * 2")
new_plot(PlotSpec(kind="2D Scatter", x="Demand X", y="Demand Y", color="Meltpool"), ("all", None, None))
w._run("derive", name="tmp", expr="[layer] + 1"); w._undo()          # undone: drops out, plot stays
new_plot(PlotSpec(kind="Histogram", x="dbl", y="count", bins=20), ("range", layers[0], layers[2]))
export(os.path.join(TMP, "rec_before.xlsx"))
w._run("filter_add", condition="[Meltpool] > 300")
export(os.path.join(TMP, "rec_after.xlsx"))
new_plot(PlotSpec(kind="Layer Viewer", x="Demand X", y="Demand Y", color="dbl"), ("single", cur, cur))
w._undo(); w._redo()                                                 # filter: undone then redone, order kept
drain()
assert R.count() == 7, R.count()
recorded = state(); n_rec_plots = len(w._plot_tabs) - base_plots; assert n_rec_plots == 3
n_before, n_after = rows(os.path.join(TMP, "rec_before.xlsx")), rows(os.path.join(TMP, "rec_after.xlsx"))
assert 0 < n_after < n_before, (n_before, n_after)
files["save"] = [os.path.join(TMP, "outputs")]; w._toggle_macro_recording()
doc = json.load(open(os.path.join(TMP, "outputs.macro.json")))
ops = [x["op"] for x in doc["steps"]]
assert ops == ["derive", "plot", "plot", "export_excel", "filter_add", "export_excel", "plot"], ops
P = [x["params"] for x in doc["steps"]]
assert P[1]["spec"]["color"] == SRC and P[1]["span"] == ["all", None, None], P[1]
assert P[2]["spec"]["x"] == "dbl" and P[2]["span"] == ["range", layers[0], layers[2]]
assert "path" not in P[3] and P[3]["filename"] == "rec_before.xlsx" and P[3]["columns"] == ["Demand X", SRC], P[3]
print("recorded:", ops)

# --- replay from the starting state (plots closed) -------------------------
while state() != base: w._undo()
for tab in list(w._plot_tabs): w._close_plot(tab)
assert not w._plot_tabs
w._run("rename", old="Meltpool", new="Pool")    # this build now calls the column something else
start = state(); n_undo = len(A.history._undo)
mfile = os.path.join(TMP, "outputs.macro.json")
out1, out2 = os.path.join(TMP, "run_before"), os.path.join(TMP, "run_after.xlsx")
files["open"] = [mfile]; files["save"] = [out1, out2]
w._run_macro(); assert not popups, popups
kinds = [t.spec.kind for t in w._plot_tabs]
assert kinds == ["2D Scatter", "Histogram", "Layer Viewer"], kinds
assert w.stack.currentWidget() is w._plot_tabs[-1], "should end on the last plot it opened"
assert w._plot_tabs[0].spec.color == "Pool" and w._plot_tabs[1].spec.x == "dbl"
drain()
assert all(t.raw is not None and t.raw.height > 0 for t in w._plot_tabs), "plots were not fed"
assert rows(out1 + ".xlsx") == n_before and rows(out2) == n_after, (rows(out1 + ".xlsx"), rows(out2), n_before, n_after)
hdr = [x.value for x in next(load_workbook(out2, read_only=True).active.iter_rows())]
assert hdr == ["Demand X", "Pool"], hdr
assert len(A.history._undo) == n_undo + 1
w._undo(); assert state() == start and len(w._plot_tabs) == 3, "undo reverts the columns, plots stay"
print(f"replayed: 3 plots fed, exports {n_before} rows (before the filter) and {n_after} (after), as recorded")

# --- pre-check: output steps with problems are listed, nothing opens --------
for tab in list(w._plot_tabs): w._close_plot(tab)
bad = [
    step("plot", spec=dict(kind="2D Scatter", x="Demand X", y="Ghost", color="dbl"), span=["all", None, None]),   # 1: two columns
    step("plot", spec=dict(kind="Histogram", x="Demand X", y="count"), span=["range", layers[0], layers[-1] + 50]),  # 2: range
    step("plot", spec=dict(kind="Single Layer", x="Demand X", y="Demand Y"), span=["single", 99999, 99999]),      # 3: layer
    step("plot", spec=dict(kind="Layer Viewer", x="Demand X", y="Demand Y"), span=["single", 99999, 99999]),      # 4: fine (start layer adapts)
    step("plot", spec=dict(kind="Pie", x="Demand X", y="Demand Y"), span=["all", None, None]),                    # 5: type
    step("plot", spec=dict(kind="Bar", x="Demand X", why="?"), span=["all", None, None]),                         # 6: bad settings
    step("export_excel", mode="summary", key="nope", values=[["Pool", "mean"], ["zip", "max"]], scope=["all", None, None]),  # 7
    step("export_excel", mode="raw", columns=["Demand X", "gone"], scope=["range", 0, 3]),                        # 8: column + range
    step("export_excel", mode="raw", columns=["Demand X"], scope=["current", 5, 5]),                              # 9: fine
]
f = os.path.join(TMP, "bad.macro.json"); macros.save(f, "bad", bad)
files["open"] = [f]; popups.clear(); w._run_macro()
flagged = [int(x.split()[1]) for x in popups[0]]
assert flagged == [1, 2, 3, 5, 6, 7, 8], flagged
assert popups[0][0].count("•") == 2 and popups[0][5].count("•") == 2 and popups[0][6].count("•") == 2, popups[0]
assert not w._plot_tabs and state() == start
print("output-step issues listed (steps):", flagged)
for x in (popups[0][1], popups[0][2], popups[0][6]): print("   ", x.replace("\n", "  "))

# --- a run that fails after opening a plot takes the plot back --------------
failed, msg, _ = A.run_batch("t", [
    ("derive", {"name": "k", "expr": "[layer] * 2"}),
    ("plot", {"spec": dict(kind="2D Scatter", x="Demand X", y="k"), "span": ["all", None, None]}),
    ("derive", {"name": "k2", "expr": "[missing] * 2"})])
for _ in range(20): app.processEvents()
assert failed == 2 and not w._plot_tabs and state() == start, (failed, len(w._plot_tabs))
drain()
print("ALL STAGE-4 CHECKS PASS")
try: c.shutdown()
except RuntimeError: pass
