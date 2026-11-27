"""One point per part, a trend line, and exports of every row.

A per-part measurement ("Distortion", from the samples template) against the
mean melt pool of each part's rows: the New plot dialog's "One point per",
the X / Y statistics (mean, CoV...), the trend line (its equation, R², p
checked against scipy), its toolbar toggle and its element (style, position),
renames of the columns it uses, Mean ± SD with a trend line, a macro step that
records and replays it. Then Export to Excel: every row, not a plot's sample
(the plot budget is lowered here so this build is sampled), only the columns
it needs, and a raw export too big for a sheet refused."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import json, os, sys, time
from pathlib import Path
BUILD = sys.argv[1]
import numpy as np
import polars as pl
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog
app = QApplication([])
from openpyxl import load_workbook
from scipy import stats
from ohpal.ampm.template import make_template
from ampm_viewer.shell import controller as cmod, excel_dialog, export, macro_dialog, plotdata, toolbars
from ampm_viewer.shell.plot_dialog import NewPlotDialog
from ampm_viewer.shell.plotspec import MEAN_SD, SCATTER_2D, PlotSpec
from ampm_viewer.shell.window import MainWindow
cmod._tell = lambda *a, **k: None
cmod._PLOT_SAMPLE_ROWS = 200_000          # this build (~870k rows) is sampled for plots
TMP = str(_harness.ROOT)
w = MainWindow(); w.resize(1300, 800); w.show(); c, s = w.controller, w.session


def drain():
    t0 = time.time()
    while time.time() - t0 < 300:
        app.processEvents()
        if not c._queue and c._current is None and not c._busy:
            for _ in range(20): app.processEvents(); time.sleep(0.002)
            if not c._queue and c._current is None and not c._busy: return
        time.sleep(0.01)
    raise SystemExit("queue never drained")


loop = QEventLoop(); s.queryReady.connect(lambda *_: loop.quit())
QTimer.singleShot(240000, loop.quit); c.open_recent(BUILD); loop.exec(); drain()
pid = c.part_id_display()
SRC = "MeltVIEW melt pool (mean)"
MP = s.renames.get(SRC, SRC)

# Every row of the build, for the true per-part means (the store, unsampled).
full = s.store.query(columns=[SRC, "part_id"], sample_to=None)
full = full.filter(pl.col("part_id").is_not_null())
true_mean = {str(k): v for k, v in full.group_by("part_id").agg(pl.col(SRC).mean()).iter_rows()}

# The samples template with a per-part "Distortion": a line in the part's mean
# melt pool, plus noise, so the trend is there to find.
root = Path(BUILD)
xlsx = make_template(next(root.glob("*.dhxml")), _harness.ROOT / "samples.xlsx",
                     quant=next(root.glob("*.csv")))
wb = load_workbook(xlsx); ws = wb.worksheets[0]
n0 = len([x.value for x in ws[1]])
ws.cell(row=1, column=n0 + 1, value="Distortion")
rng = np.random.default_rng(3)
for r in range(2, ws.max_row + 1):
    part = str(ws.cell(row=r, column=2).value)
    key = next((k for k in true_mean if k == part or k.endswith(f"({part})") or k == f"Part({part})"), None)
    m = true_mean.get(key, 250.0)
    ws.cell(row=r, column=n0 + 1, value=float(4.0 * m - 300 + rng.normal(0, 15)))
wb.save(xlsx)
for col in ("Hatch Speed", "Distortion"):
    mapping, dtype, _n = excel_dialog.parse_mapping(xlsx, ws.title, "part_id", col)
    assert w._run("excel_import", name=col, key=pid, mapping=mapping, dtype=dtype), col
    drain()

# --- the dialog -----------------------------------------------------------
cols = list(w._data_tab._columns)
dlg = NewPlotDialog(SCATTER_2D, cols, layers=list(s.store.layers), current_layer=s.current_layer,
                    renames=s.renames)
assert dlg.per_combo.currentText() == "Every row" and dlg.x_stat.isHidden() and dlg.y_stat.isHidden()
assert dlg.radio_single.isChecked(), "a 2D scatter starts on the layer on screen"
assert dlg.spec().per is None and not dlg.spec().fit
dlg.per_combo.setCurrentText(pid)
assert not dlg.x_stat.isHidden() and not dlg.y_stat.isHidden()
assert dlg.radio_all.isChecked(), "a part is wanted whole: All layers"
dlg.x_combo.setCurrentText(MP); dlg.y_combo.setCurrentText("Distortion")
dlg.fit_chk.setChecked(True)
sp = dlg.spec()
assert (sp.per, sp.x, sp.y, sp.x_stat, sp.y_stat, sp.fit) == (pid, MP, "Distortion", "mean", "mean", True), sp
assert dlg.span() == ("all", None, None)
print("dialog: One point per + statistics (hidden for every row), All layers, trend line")

# --- the plot ---------------------------------------------------------------
w._open_plot(sp, dlg.span()); drain()
tab = w._active_plot
for _ in range(40): app.processEvents()
assert tab.raw.height <= 1.05 * cmod._PLOT_SAMPLE_ROWS, "a plot's query is sampled"
rows = tab._hover_rows
n_parts = len(true_mean)
assert rows.height == n_parts, (rows.height, n_parts)
shaped = c.shape(tab.raw)
want = {str(k): v for k, v in shaped.filter(pl.col(pid).is_not_null())
        .group_by(pid).agg(pl.col(MP).mean()).iter_rows()}
for g, x, y in rows.select(plotdata.PER_GROUP, plotdata.PER_X, plotdata.PER_Y).iter_rows():
    assert abs(x - want[str(g)]) < 1e-6 * abs(want[str(g)]), (g, x, want[str(g)])  # (f32 vs f64)
    assert np.isfinite(y)
xs, ys = rows[plotdata.PER_X].to_numpy(), rows[plotdata.PER_Y].to_numpy()
ref = stats.linregress(xs, ys)
fit = tab._fit
assert abs(fit.slope - ref.slope) < 1e-9 and abs(fit.p - ref.pvalue) < 1e-9 and fit.n == n_parts
assert abs(fit.r2 - ref.rvalue ** 2) < 1e-9 and fit.r2 > 0.8, fit
text = tab._fit_text()
sign = "-" if ref.intercept < 0 else "+"
assert text[0] == f"y = {plotdata._sig(ref.slope)}x {sign} {plotdata._sig(abs(ref.intercept))}", text
assert text[1] == f"R² = {ref.rvalue ** 2:.2f}, p {plotdata.p_text(ref.pvalue)}", text
assert tab._auto_text("xaxis") == f"Mean of {MP}" and tab._auto_text("yaxis") == "Distortion", \
    "a per-part column is named plainly"
keys = [ctl.key for ctl in tab.controls()]
assert "fit" in keys and "equal_axes" not in keys, keys
assert tab._base_size == 8, "a few points: drawn big, as Mean ± SD"
assert "fit" in tab.element_keys()
# The label in its corner of the plot area (offscreen, the canvas isn't laid
# out for real, so this checks the placement against the view's own size).
from ampm_viewer.shell.plot_tab import _LEGEND_INSET
INSET = _LEGEND_INSET + 2
vw, vh = (float(v) for v in tab._view.size)
bw, bh = tab._fit_box
assert bw > 50 and bh > 15, tab._fit_box
assert tab._fit_origin == (INSET, INSET), "top left"
view = tab._widget_rect(tab._view)
tab._rect_cache.clear(); r1 = tab._element_rect("fit")
assert abs(r1.left() - (view.left() + INSET - 6)) < 1e-6 and abs(r1.width() - (bw + 12)) < 1e-6
row0 = rows.row(0, named=True)
tip = tab._per_text(row0)
assert tip.startswith(f"{pid}: ") and f"Mean of {MP}: " in tip and "rows: " in tip, tip
print(f"plot: {n_parts} parts, X = each part's mean {MP} over the plot's rows; "
      f"trend {text[0]} / {text[1]} = scipy")

# the element: position, what it shows, the line
tab._el_style["fit"].update(place="bottom_right", n=True, equation=False, dashed=False)
tab._apply_element("fit"); tab._rect_cache.clear(); app.processEvents()
bw, bh = tab._fit_box
ox, oy = tab._fit_origin
assert abs(ox + bw - (vw - INSET)) < 1e-6 and abs(oy + bh - (vh - INSET)) < 1e-6, "bottom right"
assert tab._fit_text() == [f"R² = {ref.rvalue ** 2:.2f}, p {plotdata.p_text(ref.pvalue)}, n = {n_parts}"]
assert tab._fit_line.parent is not None
ap = tab.appearance()
assert ap["elements"]["fit"]["place"] == "bottom_right", "kept with the plot (pop-out, library)"
# the toolbar toggle
w.stack.setCurrentWidget(tab); app.processEvents()
assert toolbars.press(w.toolbar, "Trend line")
assert not tab.spec.fit and not tab._element_present("fit") and tab._fit_line.parent is None
assert toolbars.press(w.toolbar, "Trend line") and tab.spec.fit and tab._element_present("fit")
print("element: corner, fields and line style; toolbar toggles it")

# CoV per part, from the same rows
w._open_plot(PlotSpec(kind=SCATTER_2D, x=MP, y="Distortion", per=pid, x_stat="cov", fit=True),
             ("all", None, None)); drain()
tab2 = w._active_plot
cov = {str(k): v for k, v in c.shape(tab2.raw).filter(pl.col(pid).is_not_null()).group_by(pid)
       .agg(100 * pl.col(MP).std() / pl.col(MP).mean()).iter_rows()}
for g, x in tab2._hover_rows.select(plotdata.PER_GROUP, plotdata.PER_X).iter_rows():
    assert abs(x - cov[str(g)]) < 1e-5 * abs(cov[str(g)]), (g, x, cov[str(g)])
assert tab2._auto_text("xaxis") == f"CoV of {MP} (%)"
print("CoV: 100 x SD / mean of each part's rows")

# renames follow
w._run("rename", old="Distortion", new="Dist"); drain()
w._run("rename", old=pid, new="Specimen"); drain()
assert tab.spec.y == "Dist" and tab.spec.per == "Specimen", tab.spec
for _ in range(20): app.processEvents()
assert tab._hover_rows.height == n_parts and tab._fit is not None
w._run("rename", old="Specimen", new=pid); drain()
w._run("rename", old="Dist", new="Distortion"); drain()
print("renames: the plot's columns, group column included, follow")

# Mean ± SD with a trend line: through the group means
w._open_plot(PlotSpec(kind=MEAN_SD, x="Hatch Speed", y="Distortion", group_by=pid, fit=True),
             ("all", None, None)); drain()
tab3 = w._active_plot
g = tab3._hover_rows
ref3 = stats.linregress(g[plotdata.MS_X].to_numpy(), g[plotdata.MS_MEAN].to_numpy())
assert abs(tab3._fit.slope - ref3.slope) < 1e-9 and tab3._element_present("fit")
assert "fit" in [ctl.key for ctl in tab3.controls()]
print("Mean ± SD: the trend line through the group means")

# --- a macro records and replays it ----------------------------------------------
files = {"save": [], "open": []}
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (files["save"].pop(0), ""))
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (files["open"].pop(0), ""))
macro_dialog.MacroPreviewDialog.exec = lambda self: QDialog.DialogCode.Accepted
macro_dialog.MacroSaveDialog.exec = lambda self: QDialog.DialogCode.Accepted
from ampm_viewer.shell import plot_dialog
rec_spec = PlotSpec(kind=SCATTER_2D, x=MP, y="Distortion", per=pid, y_stat="median", fit=True)
plot_dialog.NewPlotDialog.exec = lambda self: QDialog.DialogCode.Accepted
plot_dialog.NewPlotDialog.spec = lambda self: rec_spec
plot_dialog.NewPlotDialog.span = lambda self: ("all", None, None)
w._toggle_macro_recording()
w._new_plot(SCATTER_2D); drain()
files["save"] = [os.path.join(TMP, "per")]; w._toggle_macro_recording()
doc = json.load(open(os.path.join(TMP, "per.macro.json")))
step = doc["steps"][-1]["params"]["spec"]
assert (step["per"], step["x"], step["y_stat"], step["fit"]) == ("part_id", SRC, "median", True), step
for t in list(w._plot_tabs): w._close_plot(t)
w._run("rename", old=MP, new="Pool"); drain()
files["open"] = [os.path.join(TMP, "per.macro.json")]; w._run_macro(); drain()
rt = w._plot_tabs[-1]
assert (rt.spec.per, rt.spec.x, rt.spec.y_stat, rt.spec.fit) == (pid, "Pool", "median", True), rt.spec
assert rt._hover_rows is not None and rt._hover_rows.height == n_parts
w._run("rename", old="Pool", new=MP); drain()
print("macro: recorded with the source names, replayed under the build's")

# --- Export to Excel: every row ------------------------------------------------------
from ampm_viewer.shell import export_dialog
nxt = {}
export_dialog.ExcelExportDialog.exec = lambda self: QDialog.DialogCode.Accepted
export_dialog.ExcelExportDialog.result_values = lambda self: nxt["export"]
seen = []
orig_write = w._write_export
w._write_export = lambda spec, raw, st=None: (seen.append(raw), orig_write(spec, raw, st))[1]
out = os.path.join(TMP, "summary.xlsx")
nxt["export"] = dict(mode="summary", key=pid, values=[[MP, "mean"], ["Distortion", "as-is"]],
                     scope=("all", None, None), respect_filters=True, path=out, sheet="Export")
w._export_excel(); drain()
raw = seen[-1]
assert raw.height == s.store.query(columns=["layer"], sample_to=None).height, \
    "an export queries every row, not a plot's sample"
assert set(raw.columns) <= {SRC, "part_id", "layer", "Z", "Demand X", "Demand Y", "Start time",
                            "LaserVIEW (mean)"}, raw.columns
assert SRC in raw.columns and "MeltVIEW plasma (mean)" not in raw.columns, "only what it needs"
ws2 = load_workbook(out, read_only=True).active
got = {str(r[0]): r[1] for r in list(ws2.iter_rows(values_only=True))[1:]}
for part, m in true_mean.items():
    assert abs(got[part] - m) < 1e-6 * abs(m), (part, got[part], m)
assert any(abs(want[p] - true_mean[p]) > 1e-9 for p in true_mean), "the plot's sample differs"
print(f"export: summary from all {raw.height:,} rows ({len(raw.columns)} columns); "
      "per-part means exact")

# a raw export bigger than a sheet: refused, nothing written
export.EXCEL_MAX_ROWS = 1000
big = os.path.join(TMP, "big.xlsx")
nxt["export"] = dict(mode="raw", columns=[MP], scope=("current", s.current_layer, s.current_layer),
                     respect_filters=True, path=big, sheet="Export")
w._export_excel(); drain()
assert not os.path.exists(big)
log = w.log_bus.history()
assert "more than an Excel sheet holds (1,001 with the header)" in log, log[-400:]
assert export.columns_for(nxt["export"]) == [MP]
print("export: a raw export too big for a sheet is refused, with what to do instead")
c.shutdown()
print("ALL PER-GROUP / TREND / EXPORT CHECKS PASS")
os._exit(0)
