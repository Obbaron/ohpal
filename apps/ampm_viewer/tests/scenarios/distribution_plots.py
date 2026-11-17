"""Violin, KDE and K-distance plots: data, spec, dialog, tab, macros, app."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import sys, time
BUILD = sys.argv[1]
import numpy as np, polars as pl
from scipy.stats import gaussian_kde
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from ampm_viewer.shell import plotdata as P, macros, icons
from ampm_viewer.shell.plotspec import (PLOT_KINDS, KDE, KDIST, VIOLIN, PlotSpec, default_spec)

rng = np.random.default_rng(3)
# --- KDE maths ---------------------------------------------------------------------
v = np.concatenate([rng.normal(300, 30, 40000), rng.normal(120, 10, 4000)])
grid = np.linspace(v.min(), v.max(), 512)
for m in ("scott", "silverman"):
    ref = gaussian_kde(v, bw_method=m)
    assert abs(P.kde_bandwidth(v, m) - ref.factor * v.std(ddof=1)) < 1e-9, m
    mine = P.kde_density(v, grid, P.kde_bandwidth(v, m))
    err = np.max(np.abs(mine[::8] - ref(grid[::8]))) / ref(grid).max()
    assert err < 1e-3, (m, err)
    assert abs(np.trapezoid(mine, grid) - 1.0) < 0.01
print("KDE: bandwidths equal gaussian_kde's; density within 0.1% of it; integrates to 1")

df = pl.DataFrame({
    "MP": np.concatenate([rng.normal(300 + 5 * i, 20, 3000) for i in range(4)] + [rng.normal(0, 1, 50)]),
    "part_id": sum([[f"Part({i + 1})"] * 3000 for i in range(4)], []) + ["noise"] * 50,
})
kde = P.build_kde(df, PlotSpec(kind=KDE, x="MP", y="density", group_by="part_id"))
assert kde.names == ["Part(1)", "Part(2)", "Part(3)", "Part(4)"], kde.names
assert kde.n == 4 and kde.counts == [3000] * 4 and kde.y_name == "Density" and kde.group_name == "part_id"
assert len({tuple(c) for c in kde.colors.round(4)}) == 4
one = P.build_kde(df, PlotSpec(kind=KDE, x="MP", y="density", group_by=None))
assert one.n == 1 and one.names == ["MP"] and one.counts == [df.height]
for bad, why in ((pl.DataFrame({"MP": [5.0] * 10}), "same"), (pl.DataFrame({"MP": [1.0]}), "Not enough")):
    try: P.build_kde(bad, PlotSpec(kind=KDE, x="MP", y="density")); raise SystemExit("should fail")
    except ValueError as e: assert why in str(e), e
print("KDE curves: one per group, 'noise' dropped, single-curve mode, clear errors")

# --- violins -----------------------------------------------------------------------
vd = P.build_violins(df.filter(pl.col("part_id") != "noise"), PlotSpec(kind=VIOLIN, x="part_id", y="MP"))
assert vd.n == 4 and vd.labels == ["P1", "P2", "P3", "P4"]
part1 = df.filter(pl.col("part_id") == "Part(1)")["MP"].to_numpy()
st = vd.stats[0]
assert np.allclose([st["q1"], st["median"], st["q3"]], np.percentile(part1, [25, 50, 75]))
assert st["min"] == part1.min() and st["max"] == part1.max() and st["n"] == 3000 and st["key"] == "Part(1)"
ys, half = vd.outlines[0]
assert abs(float(half.max()) - 0.4) < 1e-6 and ys[0] == np.float32(part1.min()) and ys[-1] == np.float32(part1.max())
assert vd.full_range == (float(min(s["median"] for s in vd.stats)), float(max(s["median"] for s in vd.stats)))
flat = P.build_violins(pl.DataFrame({"c": ["a", "a"], "v": [2.0, 2.0]}), PlotSpec(kind=VIOLIN, x="c", y="v"))
assert flat.n == 1 and flat.stats[0]["median"] == 2.0
many = pl.DataFrame({"c": [str(i) for i in range(P.MAX_VIOLINS + 1)], "v": np.arange(P.MAX_VIOLINS + 1, dtype=float)})
try: P.build_violins(many, PlotSpec(kind=VIOLIN, x="c", y="v")); raise SystemExit("should fail")
except ValueError as e: assert "60 or fewer" in str(e)
print("violins: quartiles/median/range exact, same max width, one-value and too-many cases")

# --- k-distance: neighbours at full density -------------------------------------------
gx, gy = np.meshgrid(np.arange(0, 60, 0.1), np.arange(0, 60, 0.1))    # 360,000 points, 0.1 mm grid
dense = pl.DataFrame({"X": gx.ravel(), "Y": gy.ravel()})
kd = P.build_kdist(dense, PlotSpec(kind=KDIST, x="X", y="Y", z=None, k=4, eps_xy=0.15, eps_z=1.0))
assert kd.x.size == P.KDIST_SAMPLE and np.all(np.diff(kd.ys[0]) >= 0)
assert abs(float(np.median(kd.ys[0])) - 0.1) < 1e-6, np.median(kd.ys[0])   # 4th neighbour on a 0.1 grid = 0.1
assert kd.reference == 0.15 and kd.y_name == "4-distance (mm)" and kd.x_name.startswith("Rank")
# Z is stretched by eps_xy / eps_z, as DBSCAN measures it
col = pl.DataFrame({"X": np.zeros(400), "Y": np.zeros(400), "Z": np.arange(400) * 0.03})
k3 = P.build_kdist(col, PlotSpec(kind=KDIST, x="X", y="Y", z="Z", k=2, eps_xy=0.3, eps_z=0.06))
assert abs(float(np.median(k3.ys[0])) - 0.03 * 5) < 1e-9, np.median(k3.ys[0])   # 2nd neighbour = the one across: one stretched step
print("k-distance: neighbours searched among every point (median 0.1 on a 0.1 mm grid), Z scaled by eps ratio")

# --- spec + menu ---------------------------------------------------------------------
assert {KDE, KDIST, VIOLIN} <= set(PLOT_KINDS) and {KDE, KDIST, VIOLIN} <= set(icons.PLOT_TYPE)
assert not icons.for_view("Violin", "#000").isNull()
cols = ["Demand X", "Demand Y", "Z", "layer", "MeltVIEW melt pool (mean)", "part_id"]
s = default_spec(KDIST, cols, dbscan=(0.3, 0.06, 10))
assert (s.x, s.y, s.z, s.k, s.eps_xy, s.eps_z) == ("Demand X", "Demand Y", "Z", 10, 0.3, 0.06)
s = default_spec(KDE, cols); assert (s.x, s.group_by, s.uses_y) == ("MeltVIEW melt pool (mean)", "part_id", False)
s = default_spec(VIOLIN, cols); assert (s.x, s.y, s.uses_y, s.show_box) == ("part_id", "MeltVIEW melt pool (mean)", True, True)
assert PlotSpec(kind=KDE, x="a", y="density").is_curve and PlotSpec(kind=KDIST, x="a", y="b").is_curve
print("spec: kinds in the menu with icons; defaults from the build's DBSCAN settings")

# --- dialog ---------------------------------------------------------------------------
from ampm_viewer.shell.plot_dialog import NewPlotDialog
d = NewPlotDialog(KDIST, cols, [1, 2, 3], 1, dbscan=(0.25, 0.05, 8))
assert (d.k_spin.value(), round(d.epsxy_spin.value(), 3), round(d.epsz_spin.value(), 3)) == (8, 0.25, 0.05)
assert d.radio_all.isChecked() and d.epsz_spin.isEnabled()
d.z_combo.setCurrentText("None (2D)"); assert not d.epsz_spin.isEnabled() and d.spec().z is None
d.k_spin.setValue(12); assert d.spec().k == 12
d = NewPlotDialog(KDE, cols, [1, 2, 3], 1)
assert d.spec().group_by == "part_id" and d.spec().y == "density"
d.group_combo.setCurrentIndex(0); d.bw_combo.setCurrentText("Silverman")
sp = d.spec(); assert sp.group_by is None and sp.bandwidth == "silverman" and d.radio_all.isChecked()
d = NewPlotDialog(VIOLIN, cols, [1, 2, 3], 1)
d.box_chk.setChecked(False); sp = d.spec()
assert (sp.x, sp.y, sp.show_box, sp.bandwidth) == ("part_id", "MeltVIEW melt pool (mean)", False, "scott")
print("dialog: each form builds its spec; 2D disables the Z radius; all layers by default")

# --- macros ------------------------------------------------------------------------------
assert "one curve per 'part_id'" in macros.describe("plot", {"spec": {"kind": KDE, "x": "MP", "group_by": "part_id"}, "span": ["all", None, None]})
assert "of 'MP' per 'part_id'" in macros.describe("plot", {"spec": {"kind": VIOLIN, "x": "part_id", "y": "MP"}, "span": ["all", None, None]})
assert "(k = 10)" in macros.describe("plot", {"spec": {"kind": KDIST, "x": "X", "y": "Y", "z": "Z", "k": 10}, "span": ["all", None, None]})

# --- the app, on the real build ----------------------------------------------------------
from ampm_viewer.shell import controller as cmod
from ampm_viewer.shell.window import MainWindow
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
assert c.dbscan_params() == (0.3, 0.06, 10), c.dbscan_params()
menu = [a.text() for a in next(b for b in w.toolbar.findChildren(__import__("PyQt6.QtWidgets", fromlist=["QToolButton"]).QToolButton) if b.toolTip() == "New plot").menu().actions()]
assert {"Violin", "KDE", "K-Distance Curve"} <= set(menu), menu
cols = list(s.result.df.columns); MP = next(n for n in cols if "elt" in n and "ool" in n)

tk = w._open_plot(PlotSpec(kind=KDE, x=MP, y="density", group_by="part_id"), ("all", None, None)); drain()
assert tk._curve_data is not None and tk._curve_data.n == 20
assert len(tk._curve_lines) == 20 and tk._curve_fill is not None
assert tk._legend_items[0][:2] == ["Part(1)", "Part(2)"] and tk._legend_auto == "part_id"
assert tk._legend.visible and (tk._cbar is None or not tk._cbar.visible)
assert tk.panel_state()["map_only"] and not tk.panel_state()["has_color"]
cached = tk._dist_data
tk.set_colormap("viridis"); assert tk._dist_data is cached, "a recolour reuses the densities"
assert tk._curve_data.colors.shape == (20, 4)
w.tabbar.setCurrentIndex(w.stack.indexOf(tk)); app.processEvents()
w.panel.sync_plot(tk.panel_state())
assert not w.panel.colour_box.isHidden() and not w.panel.map_combo.isHidden() and w.panel.range_bar.isHidden() and w.panel.points_box.isHidden()
tv = w._open_plot(PlotSpec(kind=VIOLIN, x="part_id", y=MP), ("all", None, None)); drain()
assert tv._violin_data.n == 20 and tv._violin_marks is not None and len(tv._categories[1]) == 20
assert tv._xaxis.visible and tv._categories is not None and tv.panel_state()["has_color"] and not tv.panel_state()["map_only"]
assert "categories" in tv.element_keys()
cached = tv._dist_data; tv.set_color_min(30); assert tv._dist_data is cached and tv.crange[0] > tv._full_range[0]
td = w._open_plot(default_spec(KDIST, cols, s.renames, dbscan=c.dbscan_params()), ("all", None, None)); drain()
d = td._curve_data
assert d.n == 1 and d.reference == 0.3 and float(np.median(d.ys[0])) < 0.3, "the build's eps covers its points (full density)"
assert td._ref_line is not None and "0.3" in td._ref_label.text and td._cbar is None
assert td._xaxis.axis.axis_label.startswith("Rank") and td._yaxis.axis.axis_label == "10-distance (mm)"
print("app: menu entries; KDE legend + map-only panel + cached recolour; violins categorical + colour by median;"
      " k-distance at the build's eps (median %.3f mm < 0.3)" % float(np.median(d.ys[0])))
# a rename flows through a KDE (spec follows; data rebuilt)
out = w._run("rename", old=MP, new="MPx"); assert out.ok, out
drain(); assert tk.spec.x == "MPx" and tk._curve_data.x_name == "MPx"
w._undo(); drain()
# macro pre-check accepts a KDE (y is not a column) and flags a missing violin column
step_ok = w.actions.check_batch([("plot", {"spec": {"kind": KDE, "x": MP, "y": "density", "group_by": "part_id"}, "span": ["all", None, None]})], lambda op, p, r: p)
step_bad = w.actions.check_batch([("plot", {"spec": {"kind": VIOLIN, "x": "part_id", "y": "nope"}, "span": ["all", None, None]})], lambda op, p, r: p)
flat = lambda r: " ".join(str(x) for x in (r if isinstance(r, (list, tuple)) else [r]))
assert "Unknown column" not in flat(step_ok), step_ok
assert "nope" in flat(step_bad), step_bad
c.shutdown()
print("ALL NEW-PLOT CHECKS PASS")
