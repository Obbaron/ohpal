"""Mean ± SD (an Archimedes density plot): three densities per part from the
samples template, an energy density calculated from its laser parameters, one
point per part at its mean with a sample-SD error bar. The New plot dialog
starts on those choices; the toolbar switches the error bars; the axis editor
sets a minimum / maximum and a log scale."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import os, sys, time
from pathlib import Path
BUILD = sys.argv[1]
import numpy as np
from PyQt6.QtCore import QEventLoop, QTimer, Qt
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from openpyxl import load_workbook
from ohpal.ampm.template import make_template
from ampm_viewer.shell import controller as cmod, excel_dialog, plotdata
from ampm_viewer.shell.plot_dialog import NewPlotDialog
from ampm_viewer.shell.plotspec import MEAN_SD
from ampm_viewer.shell.window import MainWindow
cmod._tell = lambda *a, **k: None
w = MainWindow(); w.resize(1300, 800); w.show(); c, s = w.controller, w.session
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
pid = c.part_id_display()

# The template, filled in: three densities per part.
root = Path(BUILD)
xlsx = make_template(next(root.glob("*.dhxml")), _harness.ROOT / "samples.xlsx",
                     quant=next(root.glob("*.csv")))
wb = load_workbook(xlsx); ws = wb.worksheets[0]
n0 = len([c.value for c in ws[1]])
rng = np.random.default_rng(1)
dens = {}
for j in range(3):
    ws.cell(row=1, column=n0 + 1 + j, value=f"Density ({j + 1})")
for r in range(2, ws.max_row + 1):
    vals = 4.5 + rng.normal(0, 0.02, 3)
    dens[str(ws.cell(row=r, column=2).value)] = vals
    for j, v in enumerate(vals):
        ws.cell(row=r, column=n0 + 1 + j, value=float(v))
wb.save(xlsx)
for col in ("Hatches Power", "Hatch Speed", "Density (1)", "Density (2)", "Density (3)"):
    mapping, dtype, _n = excel_dialog.parse_mapping(xlsx, ws.title, "part_id", col)
    assert w._run("excel_import", name=col, key=pid, mapping=mapping, dtype=dtype), col
    drain()
w._run("derive", name="Energy density", expr="[Hatches Power] * 1000 / [Hatch Speed]")
drain()

# The New plot dialog starts on the right choices.
cols = list(w._data_tab._columns)
dlg = NewPlotDialog(MEAN_SD, cols, renames=s.renames)
sp = dlg.spec()
assert (sp.x, sp.values, sp.group_by, sp.error) == (
    "Energy density", ["Density (1)", "Density (2)", "Density (3)"], pid, "sd"), sp
# Ticking one repeat ticks its set; nothing ticked: no Plot.
items = {dlg.values_list.item(i).text(): dlg.values_list.item(i)
         for i in range(dlg.values_list.count())}
for name in ("Density (1)", "Density (2)", "Density (3)"):
    items[name].setCheckState(Qt.CheckState.Unchecked)
assert not dlg._ok.isEnabled()
items["Density (2)"].setCheckState(Qt.CheckState.Checked)
assert dlg.spec().values == ["Density (1)", "Density (2)", "Density (3)"] and dlg._ok.isEnabled()
assert dlg.span() == ("all", None, None), "the whole build: every part"

# The plot: one point per part, at its mean, with its sample SD.
w._open_plot(sp, dlg.span()); drain()
tab = w._active_plot
for _ in range(40): app.processEvents(); time.sleep(0.01)
rows = tab._hover_rows
assert rows is not None and rows.height == len(dens), (rows, len(dens))
for row in rows.iter_rows(named=True):
    part = str(row[plotdata.MS_GROUP]).removeprefix("Part(").removesuffix(")")
    vals = dens[part]
    assert abs(row[plotdata.MS_MEAN] - vals.mean()) < 1e-9
    assert abs(row[plotdata.MS_ERR] - vals.std(ddof=1)) < 1e-9 and row[plotdata.MS_N] == 3
assert tab._err_line is not None and tab._err_caps is not None
assert tab._auto_text("yaxis") == "Density" and not tab._equal_axes
tip = tab._hover_text(0)
assert "Density: " in tip and "± " in tip and "(SD)" in tip and "n: 3" in tip, tip
print(tip.replace("\n", " | "))

# Toolbar: the error bars.
keys = [ctl.key for ctl in tab.controls()]
assert "error" in keys and "equal_axes" not in keys, keys
tab.set_control("error", "se"); drain()
r0 = tab._hover_rows.row(0, named=True)
assert abs(r0[plotdata.MS_ERR] - r0[plotdata.MS_SD] / np.sqrt(3)) < 1e-9
assert "(SE)" in tab._hover_text(0) and "SD: " in tab._hover_text(0)
tab.set_control("error", "sd"); drain()

# Axis editor: Minimum / Maximum and Log scale.
fields = [f.name for f in tab.element_schema("yaxis").fields]
assert {"min", "max", "log"} <= set(fields), fields
tab.set_element("yaxis", "min", 4.3); tab.set_element("yaxis", "max", 4.7)
tab.set_element("xaxis", "min", 0.0)
for _ in range(10): app.processEvents()
rect = tab._view.camera.rect
assert abs(rect.bottom - 4.3) < 1e-6 and abs(rect.top - 4.7) < 1e-6, (rect.bottom, rect.top)
assert abs(rect.left - 0.0) < 1e-6, rect.left
tab.set_element("xaxis", "log", True); drain()
for _ in range(10): app.processEvents()
xs = tab._last_pos[:, 0]
assert np.allclose(10 ** xs, tab._hover_rows[plotdata.MS_X].to_numpy(), rtol=1e-5), "x in log10"
assert tab._view.camera.rect.left > 0, "a minimum of 0 can't be on a log axis: automatic"
for _ in range(20): app.processEvents(); time.sleep(0.01)
for ax in (tab._xaxis, tab._yaxis):  # as drawing does (headless may not draw)
    ax.axis.ticker._get_tick_frac_labels()
for _ in range(20): app.processEvents(); time.sleep(0.01)
assert tab._log_grid is not None and not tab._gridlines.visible, "the grid follows the log ticks"
fr, _minor, labels = tab._log_ticks(tab._xaxis.axis, 0, "auto", 2)
assert labels and all(float(x) > 0 for x in labels), labels
tab.set_element("xaxis", "log", False); drain()
for _ in range(20): app.processEvents(); time.sleep(0.01)
assert tab._log_grid is None and tab._gridlines.visible
tab.set_element("xaxis", "log", True); drain()
# Kept with the plot (pop out and back keep it), not as a default.
app_ = tab.appearance()["elements"]
assert app_["yaxis"]["min"] == 4.3 and app_["xaxis"]["log"] is True
from ampm_viewer.shell import plot_elements as pe
pe.save_default("yaxis", tab._el_style["yaxis"])
assert "min" not in pe.saved_default("yaxis"), "a range isn't a default for new plots"
pe.clear_defaults()

# Other plots: a 2D scatter can be logged; a bar's category axis has no range.
from ampm_viewer.shell.plotspec import PlotSpec
w._open_plot(PlotSpec(kind="Bar", x=pid, y="Density (1)", agg="mean"), ("all", None, None)); drain()
bar_x = [f.name for f in w._active_plot.element_schema("xaxis").fields]
bar_y = [f.name for f in w._active_plot.element_schema("yaxis").fields]
assert "min" not in bar_x and "log" not in bar_x and "min" in bar_y and "log" not in bar_y

# Macro record of the plot step keeps the repeats.
from ampm_viewer.shell import macros
p = macros.canonical("plot", {"spec": {**sp.__dict__, "more_y": list(sp.more_y)},
                              "span": ["all", None, None]}, s.renames)
assert p["spec"]["more_y"] == ["Density (2)", "Density (3)"]
assert "Density (3)" in macros.references("plot", p)
print("MEAN SD CHECKS PASS")
c.shutdown()
os._exit(0)
