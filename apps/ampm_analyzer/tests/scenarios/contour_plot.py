"""Filled-contour data: interpolation, levels, bands, labels (no GL), then the
plot tab's state under a GL context when run with xvfb."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import numpy as np, polars as pl
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from ampm_analyzer.shell import plotdata as P, plot_elements as pe
from ampm_analyzer.shell.plotspec import PlotSpec
from ampm_analyzer.shell.plot_tab import PlotTab

speeds = [500, 1000, 1500, 2000, 2500]; powers = [150, 160, 170, 180, 190, 200]
f = lambda v, p: 4.86 - 0.05 * ((v - 1400) / 900) ** 2 - 0.2 * max(0, (v - 1700) / 800) * max(0, (185 - p) / 35)
rows = [(v, p, f(v, p)) for p in powers for v in speeds]
df = pl.DataFrame(rows, schema=["S", "P", "D"], orient="row")
spec = PlotSpec(kind="Contour", x="S", y="P", z="D")

# --- the surface ---------------------------------------------------------------
d = P.build_contour(df, spec)
assert d.z.shape == (6, 5) and d.n == 30 and d.field.shape == (P.CONTOUR_RES,) * 2
assert d.extent == (500.0, 2500.0, 150.0, 200.0) and np.isfinite(d.field).all()
fx = np.linspace(500, 2500, P.CONTOUR_RES); fy = np.linspace(150, 200, P.CONTOUR_RES)
at = lambda v, p: float(d.field[np.abs(fy - p).argmin(), np.abs(fx - v).argmin()])
assert max(abs(at(v, p) - z) for v, p, z in rows) < 2e-3, "the surface passes through the measured values"
zmin, zmax = min(r[2] for r in rows), max(r[2] for r in rows)
assert d.field.min() >= zmin - 1e-6 and d.field.max() <= zmax + 1e-6, "never beyond what was measured"
assert abs(d.crange[0] - zmin) < 1e-6 and abs(d.crange[1] - zmax) < 1e-6
# smooth: far more distinct values than the 30 measured cells
assert len(np.unique(np.round(d.field, 4))) > 200
# rows sharing a combination are averaged; one overlay point per combination
dup = pl.concat([df, df.with_columns(pl.col("D") + 0.02)])
d2 = P.build_contour(dup, spec)
assert d2.points.shape == (30, 2) and abs(float(d2.z[0, 0]) - (f(500, 150) + 0.01)) < 1e-6
# an incomplete set: interpolated inside, blank outside, no invented corner
part = df.filter(~((pl.col("S") >= 2000) & (pl.col("P") >= 190)))
d3 = P.build_contour(part, spec)
assert np.isnan(d3.field[-1, -1]) and np.isfinite(d3.field[0, 0]) and 0.02 < np.isnan(d3.field).mean() < 0.3
assert np.nanmin(d3.field) >= zmin - 1e-6
# degenerate inputs never raise
one = P.build_contour(df.head(1), spec); assert one.n == 1 and one.field.shape[0] == P.CONTOUR_RES
line = P.build_contour(df.filter(pl.col("P") == 150), spec); assert line.n == 5
empty = P.build_contour(df.head(0), spec); assert empty.n == 0
try: P.build_contour(df.with_columns(pl.col("S").cast(pl.Utf8)), spec); raise SystemExit("text X should be refused")
except ValueError: pass
print("surface: through the points, within the measured range, mean of duplicates, blank outside, robust")

# --- levels, bands, labels ---------------------------------------------------------
for lo, hi in [(4.62, 4.89), (0, 1), (74, 535), (0.021, 0.187), (-3.2, 7.9), (1e-5, 3e-5), (120000, 910000), (5, 5)]:
    L = P.nice_levels(lo, hi)
    assert L[0] <= lo + 1e-12 and L[-1] >= hi - 1e-12 and 1 <= len(L) - 1 <= 18, (lo, hi, L)
    steps = np.diff(L); assert np.allclose(steps, steps[0])
    lead = steps[0] / 10 ** np.floor(np.log10(steps[0]))
    assert min(abs(lead - m) for m in (1, 2, 3, 5, 10)) < 1e-6, (lo, hi, steps[0])
    labels = P.level_labels(L)
    assert labels[0][0] == 0 and len(labels) <= 9 and len({len(t.split(".")[-1]) if "." in t else 0 for _, t in labels}) == 1
    assert all(abs(float(t) - L[i]) < steps[0] * 1e-6 + 1e-12 for i, t in labels), (labels, L)
L = P.nice_levels(4.62, 4.89)
assert [t for _, t in P.level_labels(L)] == ["4.62", "4.66", "4.70", "4.74", "4.78", "4.82", "4.86", "4.90"]
cols = P.band_colors(L, "viridis"); assert cols.shape == (len(L) - 1, 4) and len({tuple(c) for c in cols.round(4)}) == len(cols)
img = P.band_image(d.field, P.nice_levels(*d.crange), "viridis")
assert img.shape == (P.CONTOUR_RES, P.CONTOUR_RES, 4) and len(np.unique(img.reshape(-1, 4).round(4), axis=0)) <= len(P.nice_levels(*d.crange)) - 1
img3 = P.band_image(d3.field, P.nice_levels(*d3.crange), "viridis"); assert (img3[-1, -1] == 0).all(), "blank where there is no data"
print("levels: round steps covering the range; labels share their decimals; one colour per band")

# --- contour-only defaults -----------------------------------------------------------
assert pe.builtin_style("cbar", "Contour")["num_size"] == 9 and pe.builtin_style("cbar")["num_size"] == 12
assert pe.default_style("cbar", "2D Scatter")["num_size"] == 12
pe.save_default("cbar", {**pe.builtin_style("cbar"), "num_size": 14}); assert pe.default_style("cbar", "Contour")["num_size"] == 14, "a saved default wins"
pe.save_default("cbar", pe.builtin_style("cbar")); assert pe.default_style("cbar", "Contour")["num_size"] == 9

# --- the tab ------------------------------------------------------------------------
t = PlotTab(spec, title="c"); t.set_dataframe(df); app.processEvents()
assert t.cmap == "viridis" and t.element_values("cbar")["num_size"] == 9
assert t._contour_img is not None and t._contour_img.visible and t._contour_lines is not None and t._contour_lines.visible
lv = P.nice_levels(*t._contour_data.crange); marks = dict(P.level_labels(lv))
assert [str(x.text) for x in t._cbar.ticks] == [marks[0], marks.get(len(lv) - 1, "")]
assert [x.text for x in t._cbar_extra] == [txt for i, txt in P.level_labels(lv) if i not in (0, len(lv) - 1)]
assert tuple(float(v) for v in t._data_bounds[0]) == (500.0, 150.0) and tuple(float(v) for v in t._data_bounds[1]) == (2500.0, 200.0)
n0 = len(t._cbar_extra)
t.set_color_min(40); assert t.crange[0] > zmin and len(t._cbar_extra) > 0 and float(t._cbar_extra[0].text) >= t.crange[0] - 1e-9
t.set_colormap("turbo"); assert t.cmap == "turbo"
t.set_element("cbar", "num_size", 12); assert all(x.font_size == 12 for x in [*t._cbar.ticks, *t._cbar_extra])
t.reset_element("cbar", builtin=True); assert all(x.font_size == 9 for x in [*t._cbar.ticks, *t._cbar_extra])
t.set_dataframe(part); assert not t._contour_lines.visible, "no level lines over a surface with gaps"
t.set_dataframe(df); assert t._contour_lines.visible
t.set_legend_visible(False) if hasattr(t, "set_legend_visible") else None
# another kind keeps a continuous bar with only its end labels
s2 = PlotTab(PlotSpec(kind="2D Scatter", x="S", y="P", color="D")); s2.set_dataframe(df); app.processEvents()
assert s2._cbar_extra == [] and s2.cmap != "viridis" and s2.element_values("cbar")["num_size"] == 12
a = t.appearance(); t4 = PlotTab(spec); t4.apply_appearance(a); t4.set_dataframe(df); assert t4.cmap == "turbo"
print("tab: viridis start, banded bar labelled at the levels, recolour + restyle + gaps handled; other plots unchanged")
print("ALL CONTOUR CHECKS PASS")
