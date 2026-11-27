"""Marker shape by a column, a label by each point, X error bars.

Per-part columns from the samples template ("Orientation": three values,
"Specimen": a name per part, "Distortion"): the New plot dialog's "Shape by"
and "Label points"; a one-point-per-part scatter with a shape per orientation
and its key (beside a colour bar: inside the plot; with colour groups: a
second section; alone: the key's title), the labels beside the points (their
side, a click on one, a log axis, too many to label), the tooltip, the side
panel's marker picker; Mean ± SD with error bars on X (the toolbar toggle,
the spread of the parts' X in each group, the framing), renames, and a macro
that records and replays them."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import json, os, sys, time
from dataclasses import asdict
from pathlib import Path
BUILD = sys.argv[1]
import numpy as np
import polars as pl
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog
app = QApplication([])
from openpyxl import load_workbook
from ohpal.ampm.template import make_template
from ampm_viewer.shell import controller as cmod, excel_dialog, macro_dialog, plotdata, toolbars
from ampm_viewer.shell.plot_dialog import NewPlotDialog
from ampm_viewer.shell.plotspec import MEAN_SD, SCATTER_2D, PlotSpec
from ampm_viewer.shell.window import MainWindow
cmod._tell = lambda *a, **k: None
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


def pump(n=40):
    for _ in range(n): app.processEvents()


loop = QEventLoop(); s.queryReady.connect(lambda *_: loop.quit())
QTimer.singleShot(240000, loop.quit); c.open_recent(BUILD); loop.exec(); drain()
pid = c.part_id_display()
MP = s.renames.get("MeltVIEW melt pool (mean)", "MeltVIEW melt pool (mean)")

# Per-part columns: an orientation (0 / 67 / 90 in turn), a name, a distortion.
root = Path(BUILD)
xlsx = make_template(next(root.glob("*.dhxml")), _harness.ROOT / "samples.xlsx",
                     quant=next(root.glob("*.csv")))
wb = load_workbook(xlsx); ws = wb.worksheets[0]
n0 = len([x.value for x in ws[1]])
for j, name in enumerate(("Orientation", "Specimen", "Distortion")):
    ws.cell(row=1, column=n0 + 1 + j, value=name)
rng = np.random.default_rng(5)
for r in range(2, ws.max_row + 1):
    ws.cell(row=r, column=n0 + 1, value=(0, 67, 90)[(r - 2) % 3])
    ws.cell(row=r, column=n0 + 2, value=f"SP{r - 1}")
    ws.cell(row=r, column=n0 + 3, value=float(rng.normal(800, 100)))
wb.save(xlsx)
for col in ("Hatch Speed", "Orientation", "Specimen", "Distortion"):
    mapping, dtype, _n = excel_dialog.parse_mapping(xlsx, ws.title, "part_id", col)
    assert w._run("excel_import", name=col, key=pid, mapping=mapping, dtype=dtype), col
    drain()

# --- the dialog -----------------------------------------------------------
cols = list(w._data_tab._columns)
dlg = NewPlotDialog(SCATTER_2D, cols, layers=list(s.store.layers), current_layer=s.current_layer,
                    renames=s.renames)
from ampm_viewer.shell.plot_dialog import _NONE
assert dlg.shape_combo.currentText() == _NONE and dlg.label_combo.currentText() == _NONE, \
    (dlg.shape_combo.currentText(), dlg.label_combo.currentText())
assert dlg.spec().shape_by is None and dlg.spec().label_by is None and dlg.xerr_chk is None
dlg.per_combo.setCurrentText(pid)
dlg.x_combo.setCurrentText(MP); dlg.y_combo.setCurrentText("Distortion")
dlg.color_combo.setCurrentText("Hatch Speed")
dlg.shape_combo.setCurrentText("Orientation"); dlg.label_combo.setCurrentText("Specimen")
sp = dlg.spec()
assert (sp.per, sp.color, sp.shape_by, sp.label_by) == (pid, "Hatch Speed", "Orientation", "Specimen"), sp
ms = NewPlotDialog(MEAN_SD, cols, layers=list(s.store.layers), current_layer=s.current_layer,
                   renames=s.renames)
assert not ms.xerr_chk.isChecked() and not ms.spec().x_error
ms.xerr_chk.setChecked(True); ms.label_combo.setCurrentText("Orientation")
mspec = ms.spec()
assert mspec.x_error and mspec.label_by == "Orientation" and mspec.shape_by is None, mspec
print("dialog: Shape by, Label points (2D scatter, Mean ± SD), On X too (Mean ± SD)")

# --- shapes beside a colour bar --------------------------------------------------
w._open_plot(sp, ("all", None, None)); drain()
tab = w._active_plot
pump()
rows = tab._hover_rows
orient = dict(zip(rows[plotdata.PER_GROUP].to_list(), rows["Orientation"].to_list()))
want = {0: "disc", 67: "square", 90: "triangle_up"}
assert [want[orient[g]] for g in rows[plotdata.PER_GROUP]] == list(tab._symbols)
assert tab._shape_items == ("Orientation", ["0", "67", "90"], ["disc", "square", "triangle_up"])
assert tab._cbar_spec is not None and tab._cbar.visible, "Hatch Speed: a colour bar"
assert tab._legend is not None and tab._legend.visible, "and the shapes' key"
assert tab._legend_place() == "top_right", "no room outside beside the bar: inside"
side = tab._slots["side"].width_min
assert abs(side - tab._cbar_extent(tab._el_style["cbar"])) < 1e-6, (side, "the side cell is the bar's")
assert tab._legend_auto == "Orientation"
assert {"cbar", "legend", "labels", "data_points"} <= set(tab.element_keys()), tab.element_keys()
sizes = np.asarray(tab._scatter._data["a_size"])
tri = np.array([m == "triangle_up" for m in tab._symbols])
assert sizes[tri].min() > sizes[~tri].max() - 1e-6, "a triangle drawn bigger, to look the same size"
tip = tab._hover_text(0)
assert "Orientation: " in tip and "Specimen: " in tip, tip
w.stack.setCurrentWidget(tab); pump()
st = tab.panel_state()
assert st["shape_by"] == "Orientation"
w.panel.sync_plot(st)
assert not w.panel.marker_combo.isEnabled(), "the shapes come from a column: no marker to pick"
print(f"shapes: {len(rows)} parts, one shape per orientation; key inside beside the colour bar")

# --- the labels --------------------------------------------------------------
lab = tab._point_labels
names = rows["Specimen"].to_list()
assert lab is not None and lab.parent is not None and list(lab.text) == names
assert tuple(lab.anchors) == ("left", "center")
p, q = np.asarray(tab._last_pos, "float64"), np.asarray(lab.pos, "float64")[:, :2]
assert (q[:, 0] > p[:, 0]).all() and np.allclose(q[:, 1], p[:, 1]), "to the right, level"
o, one = (np.asarray(v)[:2] for v in tab._view.scene.transform.imap([[0, 0], [1, 0]])[:, :2])
gap = (q[0, 0] - p[0, 0]) / (one[0] - o[0])
assert abs(gap - (tab._applied_size / 2 + 4)) < 1e-3, gap
tab._el_style["labels"]["side"] = "above"; tab._apply_element("labels"); pump(5)
q = np.asarray(lab.pos, "float64")[:, :2]
assert np.allclose(q[:, 0], p[:, 0]) and (q[:, 1] > p[:, 1]).all(), "above: higher, centred"
assert tuple(lab.anchors) == ("center", "top")
# zoom: the gap stays in pixels
tab._view.camera.zoom(0.5); pump(5)
o, one = (np.asarray(v)[:2] for v in tab._view.scene.transform.imap([[0, 0], [0, 1]])[:, :2])
q2 = np.asarray(lab.pos, "float64")[:, :2]
assert abs((q2[0, 1] - p[0, 1]) / (o[1] - one[1]) - (tab._applied_size / 2 + 4)) < 1e-3
tab.reset_view(); pump(5)
tab._rect_cache.clear()
assert all(b.width() > 0 for b in tab._label_boxes())
# A click: on a label, the labels; between them (inside their outline), not.
# (Offscreen the canvas isn't laid out for real, so the boxes are set here.)
from PyQt6.QtCore import QRectF
tab._rect_cache.clear()
tab._rect_cache.update({k: None for k in tab._el_style})
tab._rect_cache.update(labels=QRectF(100, 100, 200, 60),
                       _label_boxes=[QRectF(100, 100, 30, 12), QRectF(270, 148, 30, 12)])
assert tab._element_at((110, 105)) == "labels" and tab._element_at((280, 150)) == "labels"
assert tab._element_at((200, 130)) is None, "between labels: not the labels"
tab._rect_cache.clear()
style = tab._el_style["labels"]
style.update(size=14, bold=True, color="#aa0000"); tab._apply_element("labels")
assert float(lab.font_size) == 14 and lab.bold
assert tab.appearance()["elements"]["labels"]["side"] == "above", "kept with the plot"
print("labels: beside each point, a side, a gap in pixels at any zoom, styled as an element")

# a log axis leaves points out: the shapes and labels go with them
tab._el_style["xaxis"]["log"] = True; tab._render(); pump()
assert len(tab._symbols) == len(tab._last_pos) == len(lab.text)
tab._el_style["xaxis"]["log"] = False; tab._render(); pump()
print("log axis: shapes and labels follow the points kept")

# --- with colour groups: two sections; alone: its own title ----------------------
w._open_plot(PlotSpec(kind=SCATTER_2D, x=MP, y="Distortion", per=pid, color="Specimen",
                      shape_by="Orientation"), ("all", None, None)); drain()
t2 = w._active_plot; pump()
assert t2._legend_items is not None and t2._shape_items is not None
assert t2._cbar_spec is None and (t2._cbar is None or not t2._cbar.visible)
assert t2._legend_place() == "outside" and t2._legend_auto == "Specimen"
assert abs(t2._slots["side"].width_min - (t2._legend_size[0] + 6.0)) < 1e-6
texts = [getattr(p, "text", None) for p in t2._legend_parts]
# (offscreen the plot is a few pixels tall: each section shows a count)
assert texts[0] == "Specimen" and "Orientation" in texts[1:], texts
assert np.allclose(t2._shape_rgba(), [0.42, 0.45, 0.5, 1.0]), "coloured by groups: grey shapes"
w._open_plot(PlotSpec(kind=SCATTER_2D, x=MP, y="Distortion", per=pid, shape_by="Orientation"),
             ("all", None, None)); drain()
t3 = w._active_plot; pump()
assert t3._legend_items is None and t3._cbar_spec is None and t3._legend.visible
assert t3._legend_auto == "Orientation" and "legend" in t3.element_keys()
assert np.allclose(t3._shape_rgba(), t3._last_colors[0]), "one colour: the shapes in it"
assert "Legend" in [ctl.label for ctl in t3.controls()]
w.stack.setCurrentWidget(t3); pump()
assert toolbars.press(w.toolbar, "Legend") and not t3._legend.visible
assert toolbars.press(w.toolbar, "Legend") and t3._legend.visible
print("key: a second section under colour groups; its own box (and Legend toggle) alone")

# every row: shapes on all, labels only up to LABEL_MAX
w._open_plot(PlotSpec(kind=SCATTER_2D, x=MP, y="Distortion", shape_by="Orientation", label_by="Specimen"),
             ("single", s.current_layer, s.current_layer)); drain()
t4 = w._active_plot; pump()
assert t4._symbols is not None and len(t4._symbols) == len(t4._last_pos)
assert len(t4._last_pos) > plotdata.LABEL_MAX and t4._point_texts is None
assert "labels" not in t4.element_keys(), "too many points to label"
print(f"every row: {len(t4._last_pos):,} points shaped, too many to label")

# --- Mean ± SD with X error bars --------------------------------------------------
w._open_plot(PlotSpec(kind=MEAN_SD, x=MP, y="Distortion", group_by="Orientation",
                      label_by="Orientation"), ("all", None, None)); drain()
t5 = w._active_plot; pump()
assert t5._err_xline is None and t5._el_style["labels"]["side"] == "above_right"
keys = [ctl.key for ctl in t5.controls()]
assert keys.index("error") < keys.index("x_error") < keys.index("fit"), keys
w.stack.setCurrentWidget(t5); pump()
assert toolbars.press(w.toolbar, "Error bars on X") and t5.spec.x_error
pump()
g = t5._hover_rows
shaped = c.shape(t5.raw).filter(pl.col(pid).is_not_null())
per_part = shaped.group_by(["Orientation", pid]).agg(pl.col(MP).mean())
for grp, xe in zip(g[plotdata.MS_GROUP].to_list(), g[plotdata.MS_X_ERR].to_list()):
    xs = per_part.filter(pl.col("Orientation") == grp)[MP].to_numpy()
    assert abs(xe - np.std(xs, ddof=1)) < 1e-4 * max(1.0, xe), (grp, xe, np.std(xs, ddof=1))
assert t5._err_xline is not None and t5._err_xcaps is not None
lo, hi = t5._err_xextent
mx = g[plotdata.MS_X].to_numpy(); xe = g[plotdata.MS_X_ERR].to_numpy()
assert abs(lo - (mx - xe).min()) < 1e-3 and abs(hi - (mx + xe).max()) < 1e-3
t5.reset_view(); pump(5)
rect = t5._view.camera.rect
assert rect.left < lo and rect.right > hi, "framed to take the bars in"
assert "±" in t5._meansd_text(g.row(0, named=True)).split("\n")[1]
assert toolbars.press(w.toolbar, "Error bars on X") and not t5.spec.x_error and t5._err_xline is None
assert toolbars.press(w.toolbar, "Error bars on X")
print("Mean ± SD: X error bars from the parts' spread in each group; toolbar toggle; framing")

# renames follow
w._run("rename", old="Orientation", new="Build angle"); drain(); pump()
assert t5.spec.group_by == "Build angle" and t5.spec.label_by == "Build angle"
assert t3.spec.shape_by == "Build angle" and t3._legend_auto == "Build angle"
w._run("rename", old="Build angle", new="Orientation"); drain()
print("renames: shape and label columns follow")

# saved with the plot (library / pop-out)
assert PlotSpec(**asdict(t5.spec)) == t5.spec

# --- a macro records and replays them ------------------------------------------
files = {"save": [], "open": []}
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (files["save"].pop(0), ""))
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (files["open"].pop(0), ""))
macro_dialog.MacroPreviewDialog.exec = lambda self: QDialog.DialogCode.Accepted
macro_dialog.MacroSaveDialog.exec = lambda self: QDialog.DialogCode.Accepted
from ampm_viewer.shell import plot_dialog
rec_spec = PlotSpec(kind=MEAN_SD, x=MP, y="Distortion", group_by="Orientation",
                    shape_by="Orientation", label_by=pid, x_error=True)
plot_dialog.NewPlotDialog.exec = lambda self: QDialog.DialogCode.Accepted
plot_dialog.NewPlotDialog.spec = lambda self: rec_spec
plot_dialog.NewPlotDialog.span = lambda self: ("all", None, None)
w._toggle_macro_recording()
w._new_plot(MEAN_SD); drain()
files["save"] = [os.path.join(TMP, "marks")]; w._toggle_macro_recording()
with open(os.path.join(TMP, "marks.macro.json")) as f:
    doc = json.load(f)
step = doc["steps"][-1]
p = step["params"]["spec"]
assert (p["shape_by"], p["label_by"], p["x_error"]) == ("Orientation", "part_id", True), p
for t in list(w._plot_tabs): w._close_plot(t)
w._run("rename", old=pid, new="Part"); drain()
files["open"] = [os.path.join(TMP, "marks.macro.json")]; w._run_macro(); drain()
rt = w._plot_tabs[-1]; pump()
assert (rt.spec.shape_by, rt.spec.label_by, rt.spec.x_error) == ("Orientation", "Part", True), rt.spec
assert rt._symbols is not None and rt._err_xline is not None and rt._point_texts
w._run("rename", old="Part", new=pid); drain()
print("macro: recorded with the source names, replayed under the build's")
c.shutdown()
print("ALL POINT MARK CHECKS PASS")
os._exit(0)
