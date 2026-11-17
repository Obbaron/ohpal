"""Editable plot elements, the finishing touches: axis ticks, lines and
gridlines; the colour bar's position, gap, thickness and numbers; the title's
alignment; the legend box; the data as an element; hidden elements give their
room to the plot. On the real build, under a GL context (xvfb on Linux), so
the canvas is laid out at its real size."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import sys, time
BUILD = sys.argv[1]
import numpy as np
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from ampm_analyzer.shell import controller as cmod, plot_elements as pe
from ampm_analyzer.shell.plotspec import PlotSpec
from ampm_analyzer.shell.window import MainWindow
cmod._tell = lambda *a, **k: None
w = MainWindow(); w.resize(1200, 760); w.show(); c, s = w.controller, w.session
panel = w.panel
ctl = lambda name: panel._el_controls[name][1]
ALL = ("all", None, None)

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
wait_ready(lambda: c.open_recent(BUILD)); drain()
cols = list(s.result.df.columns); X, Y = "Demand X", "Demand Y"
MP = next(n for n in cols if "elt" in n and "ool" in n)

# --- the schema ----------------------------------------------------------------------
assert pe.nice_ticks(0, 1, 5) == [0.0, 0.25, 0.5, 0.75, 1.0]
assert pe.nice_ticks(0, 1000, 11) == [0.0] + [100.0 * i for i in range(1, 11)]
assert pe.nice_ticks(1, 1, 5) == [] and pe.nice_ticks(0, 1, 1) == []
assert pe.format_number(1234.5, "fixed", 1) == "1234.5" and pe.format_number(1234.5, "sci", 2) == "1.23e+03"
assert pe.format_number(0.5, "auto", 3) == "0.5"
assert pe._clean("xaxis", {"ticks": 99, "format": "bogus", "line": 1, "grid_opacity": -5}) == \
    {"ticks": 12, "line": True, "grid_opacity": 0}, "ints clamp to their own range, unknown choices drop"
assert pe._clean("cbar", {"orient": "bottom", "gap": 500}) == {"orient": "bottom", "gap": 80}
assert pe.data_key(PlotSpec(kind="Histogram", x=X, y="count")) == "data_bars"
assert pe.builtin_style("data_bars", "Histogram")["bar_width"] == 100 and pe.builtin_style("data_bars", "Bar")["bar_width"] == 80
assert pe.keys_for(PlotSpec(kind="KDE", x=MP, y="density"))[-2:] == ["legend", "data_curves"]
print("schema: number formats, round ticks, per-field cleaning, a data element per kind")

# --- the title's alignment --------------------------------------------------------------
tab = w._open_plot(PlotSpec(kind="2D Scatter", x=X, y=Y, color=MP), ALL); drain()
assert set(tab._el_style) == {"title", "xaxis", "yaxis", "categories", "cbar", "legend", "data_points"}
tab.elementActivated.emit("title")
assert "align" in panel._el_controls and ctl("align").currentData() == "center"
tv = tab._title_label._text_visual
assert tuple(tv.anchors)[0] == "center"
ctl("align").setCurrentIndex(ctl("align").findData("left"))
assert tab.element_values("title")["align"] == "left" and tuple(tv.anchors)[0] == "left"
assert abs(float(tv.pos[0][0]) - (tab._title_label.rect.left + 4)) < 1, tv.pos
ctl("align").setCurrentIndex(ctl("align").findData("right")); assert tuple(tv.anchors)[0] == "right"
strip = tab._widget_rect(tab._title_label)
assert abs(tab._compute_rect("title").right() - strip.right()) < 1, "the outline follows the title to the right"
print("title: left / centre / right, outline follows")

# --- axes: number of ticks, format, line, gridlines --------------------------------------
tab.elementActivated.emit("xaxis")
for name in ("ticks", "format", "decimals", "line", "line_color", "grid_color", "grid_opacity"):
    assert name in panel._el_controls, name
assert ctl("ticks").specialValueText() == "Auto" and ctl("ticks").value() == 0
ax = tab._xaxis.axis
lo, hi = (float(v) for v in ax.domain)
ctl("ticks").setValue(4); ctl("format").setCurrentIndex(ctl("format").findData("fixed")); ctl("decimals").setValue(1)
major, minor, labels = ax.ticker._get_tick_frac_labels()
assert 3 <= len(labels) <= 6 and all(l.count(".") == 1 and len(l.split(".")[1]) == 1 for l in labels), labels
want = [lo + f * (hi - lo) for f in major]
assert all(abs(float(l) - v) < 0.06 for l, v in zip(labels, want)), (labels, want)
ctl("format").setCurrentIndex(ctl("format").findData("sci"))
assert all("e" in l for l in ax.ticker._get_tick_frac_labels()[2])
ctl("ticks").setValue(0); ctl("format").setCurrentIndex(ctl("format").findData("auto"))
assert ax.ticker._get_tick_frac_labels()[2] == tab._xaxis.axis.ticker._get_tick_frac_labels()[2]
ctl("line").setChecked(True); assert str(ax.axis_color) != str(tab._yaxis.axis.axis_color), "only this axis's line"
ctl("line").setChecked(False)
ctl("grid_opacity").setValue(40)
assert tab.element_values("yaxis")["grid_opacity"] == 40, "one set of gridlines, either editor"
assert tab._grid_rgba == (0.0, 0.0, 0.0, 0.4) and tuple(tab._gridlines._grid_color_fn["color"].value) == (0.0, 0.0, 0.0, 0.4)
panel.elementReset.emit("xaxis", True)
assert tab.element_values("yaxis")["grid_opacity"] == 12 and tab._grid_rgba[3] == 0.12
print("axes: tick count + format, the axis line, shared gridlines (reset too)")

# --- the colour bar: numbers, thickness, gap, position -------------------------------------
tab.elementActivated.emit("cbar")
for name in ("num_ticks", "num_format", "num_decimals", "orient", "gap", "thickness"):
    assert name in panel._el_controls, name
assert tab._cbar_orient == "right" and tab._cbar_extra == []
width0 = tab._slots["side"].width_max
ctl("num_ticks").setValue(5)
lo, hi, _ = tab._cbar_spec
vals = [float(t.text) for t in tab._cbar_extra]
assert len(vals) >= 2 and all(lo < v < hi for v in vals), vals
ctl("num_format").setCurrentIndex(ctl("num_format").findData("sci")); ctl("num_decimals").setValue(1)
assert all("e" in str(t.text) for t in [*tab._cbar.ticks, *tab._cbar_extra])
ctl("thickness").setValue(30)
major, minor = tab._cbar._calc_size(); assert minor == min(30.0, major), (major, minor)
ctl("gap").setValue(25); assert tab._slots["gap_r"].width_max == 25
ctl("orient").setCurrentIndex(ctl("orient").findData("bottom"))
assert tab._cbar_orient == "bottom" and tab._cbar.orientation == "bottom" and tab._cbar.visible
assert tab._slots["side"].width_max == 0 and tab._slots["gap_r"].width_max == 0 and tab._slots["label_r"].width_max == 0
assert tab._slots["bar_b"].height_max > 30 and tab._slots["gap_b"].height_max == 29 and tab._slots["label_b"].height_max > 0
assert all("e" in str(t.text) for t in tab._cbar.ticks), "the numbers follow it to its new place"
assert tab._cbar_label.text == MP and tab._cbar_label._text_visual.rotation == 0
panel.elementReset.emit("cbar", True)
assert tab._cbar_orient == "right" and tab._slots["side"].width_max == width0 and tab._slots["bar_b"].height_max == 0
assert tab._cbar_extra == [] and "e" not in str(tab._cbar.ticks[0].text)
print("colour bar: numbers (count, format), thickness, gap, right <-> below the plot")

# --- hidden elements give their room to the plot --------------------------------------------
yw, xh, th, side = (tab._yaxis.width_max, tab._xaxis.height_max,
                    tab._title_label.height_max, tab._slots["side"].width_max)
assert min(yw, xh, th, side) > 0
tab.set_axes_visible(False); tab.set_legend_visible(False); tab.set_title_visible(False)
assert tab._yaxis.width_max == 0 and tab._xaxis.height_max == 0 and tab._title_label.height_max == 0
assert all(not sl.width_max and not sl.height_max for sl in tab._slots.values()), \
    {k: (v.width_max, v.height_max) for k, v in tab._slots.items()}
assert tab.element_keys() == ["data_points"]
tab.set_axes_visible(True); tab.set_legend_visible(True); tab.set_title_visible(True); app.processEvents()
assert tab._yaxis.width_max >= 30 and tab._xaxis.height_max == xh and tab._title_label.height_max == th
assert tab._slots["side"].width_max == side
print("hidden axes, title, colour bar: no room kept for them")

# --- the legend box ---------------------------------------------------------------------------
tl = w._open_plot(PlotSpec(kind="2D Scatter", x=X, y=Y, color="part_id"), ALL); drain()
assert tl.element_keys()[-2:] == ["legend", "data_points"] and "cbar" not in tl.element_keys()
assert tl._legend.parent is tl._slots["side"] and tl._slots["side"].width_max == tl._legend_size[0] + 6
texts = [p.text for p in tl._legend_parts if hasattr(p, "text")]
assert texts[0] == "part_id" and tl._legend_items[0][:3] == ["Part(1)", "Part(2)", "Part(3)"], texts
assert texts[1] in ("Part(1)", "+ 20 more"), "the rows, or as many as fit and a count"
tl.elementActivated.emit("legend")
assert panel.el_heading.text() == "Legend" and ctl("text").placeholderText() == "part_id"
for name in ("name_font", "name_size", "name_color", "place", "frame", "frame_color"):
    assert name in panel._el_controls, name
ctl("text").setText("Parts"); ctl("text").textEdited.emit("Parts")
assert [p.text for p in tl._legend_parts if hasattr(p, "text")][0] == "Parts"
w1 = tl._legend_size[0]; ctl("name_size").setValue(14); assert tl._legend_size[0] > w1, "bigger names, wider box"
ctl("place").setCurrentIndex(ctl("place").findData("top_right"))
assert tl._legend.parent is tl._view and tl._slots["side"].width_max == 0, "inside: no room taken beside"
vw = float(tl._view.size[0]); lx = float(tl._legend.pos[0])
assert abs(lx - max(0.0, vw - tl._legend_size[0] - 10)) < 1.5, (lx, vw)
ctl("place").setCurrentIndex(ctl("place").findData("bottom_left"))
assert float(tl._legend.pos[0]) == 10
ctl("frame").setChecked(False); assert tl._legend.border_width == 0
ctl("frame").setChecked(True); assert tl._legend.border_width == 1
# click it: the legend, not the data under it
r = tl._element_rect("legend"); cx, cy = r.center().x(), r.center().y()
assert tl._element_at((cx, cy)) == "legend"
tl.set_legend_visible(False); assert not tl._legend.visible and "legend" not in tl.element_keys()
tl.set_legend_visible(True); assert tl._legend.visible
print("legend box: title, names, outside / inside a corner, frame; clickable")

# --- the data as an element -------------------------------------------------------------------
tl.select_element(None); tab = w._open_plot(PlotSpec(kind="2D Scatter", x=X, y=Y, color=MP), ALL); drain()
pos = tab._scatter.get_transform("visual", "canvas").map(tab._hover_xy[0])[:2]
assert tab._element_at((float(pos[0]), float(pos[1]))) == "data_points", "a point is the data"
vr = tab._widget_rect(tab._view)
empty = next((x, y) for x in np.linspace(vr.left() + 3, vr.right() - 3, 40)
             for y in np.linspace(vr.top() + 3, vr.bottom() - 3, 40)
             if tab._hover_tree.query(tab._scatter.get_transform("canvas", "visual").map((x, y))[:2])[0] > 0
             and np.hypot(*(tab._scatter.get_transform("visual", "canvas").map(
                 tab._hover_xy[tab._hover_tree.query(tab._scatter.get_transform("canvas", "visual").map((x, y))[:2])[1]])[:2]
                 - np.array([x, y]))) > 30)
assert tab._element_at(empty) is None, "empty plot area is not the data"
tab.elementActivated.emit("data_points")
assert panel.el_heading.text() == "Points"
assert {"symbol", "size", "opacity", "cmap", "scale"} <= set(panel._el_controls)
assert ctl("size").value() == tab.marker_size() and ctl("cmap").currentData() == tab.cmap
ctl("size").setValue(9); assert tab.marker_size() == 9 and panel.size_slider.value() == 9, "the Points box follows"
ctl("cmap").setCurrentIndex(ctl("cmap").findData("viridis")); assert tab.cmap == "viridis" and panel.map_combo.currentText() == "viridis"
panel.size_slider.setValue(5); assert tab.element_values("data_points")["size"] == 5, "and the editor follows the panel"
panel.el_default_btn.click(); assert pe.saved_default("data_points") == {"size": 5, "cmap": "viridis"}, pe.saved_default("data_points")
t2 = w._open_plot(PlotSpec(kind="2D Scatter", x=X, y=Y, color=MP), ALL); drain()
assert t2.marker_size() == 5 and t2.cmap == "viridis", "new plots start from the saved data default"
t2.elementActivated.emit("data_points"); panel.elementReset.emit("data_points", True)
assert t2.marker_size() == 3 and t2.cmap == pe.builtin_style("data_points")["cmap"] and panel.size_slider.value() == 3
panel.el_default_btn.click(); assert pe.saved_default("data_points") == {}
print("data: a point clicks as the data; its editor and the Points box stay in step; defaults")

# bars: width and outline; histograms start touching
tb = w._open_plot(PlotSpec(kind="Bar", x="part_id", y=MP), ALL); drain()
assert "data_bars" in tb.element_keys() and abs(tb._bar_w - 0.8) < 1e-6
tb.set_element("data_bars", "bar_width", 50); assert abs(tb._bar_w - 0.5) < 1e-6
v = tb._bars.mesh_data.get_vertices()
assert abs((v[1, 0] - v[0, 0]) - 0.5) < 1e-5, "the drawn bars are narrower"
tb.set_element("data_bars", "outline", True)
assert tb._bar_outline is not None and tb._bar_outline.parent is not None
tb.reset_element("data_bars", builtin=True); assert tb._bar_outline.parent is None
th = w._open_plot(PlotSpec(kind="Histogram", x=MP, y="count", bins=20), ALL); drain()
d = th._bar_data; assert abs(th._bar_w - d.width) < 1e-9, "bins touch"
# curves: line width; contour lines
tk = w._open_plot(PlotSpec(kind="KDE", x=MP, y="density", group_by="part_id"), ALL); drain()
assert tk.element_keys()[-2:] == ["legend", "data_curves"]
tk.set_element("data_curves", "line_width", 5); assert all(float(l.width) == 5.0 for l in tk._curve_lines)
print("bars: width, outline; histogram bins touch; curves: line width")

# --- crowded labels: turned, thinned, never overlapping ----------------------------------------------
w._select_widget(tb); app.processEvents()
tb.elementActivated.emit("categories")
assert "angle" in panel._el_controls and ctl("angle").currentData() == "auto"
settle = lambda t: [(t._canvas.update(), app.processEvents(), time.sleep(0.02)) for _ in range(15)]
settle(tb); tb._xaxis.axis.ticker._get_tick_frac_labels()
names = tb._categories[1]; assert len(names) == 20
angle, nth, depth = tb._cat_layout
fm = tb._label_metrics(tb._el_style["categories"])
slot = float(tb._view.size[0]) / float(tb._view.camera.rect.width)
widest = max(fm.horizontalAdvance(n) for n in names)
assert (angle == 0) == (widest + 6 <= slot), (angle, widest, slot)   # turned only if they'd touch
assert tb._xaxis.axis._text.rotation == -angle
ctl("angle").setCurrentIndex(ctl("angle").findData("0"))
labels = tb._xaxis.axis.ticker._get_tick_frac_labels()[2]
shown = [l for l in labels if l]
assert tb._cat_layout[0] == 0 and (len(shown) == len(labels) or len(shown) * (widest + 6) <= slot * len(labels) + widest), \
    "flat names are thinned to fit"
flat_nth = tb._cat_layout[1]; assert flat_nth == max(1, int(np.ceil((widest + 6) / slot)))
ctl("angle").setCurrentIndex(ctl("angle").findData("90"))
tb._xaxis.axis.ticker._get_tick_frac_labels(); settle(tb)
assert tb._cat_layout[0] == 90 and tb._xaxis.axis._text.rotation == -90
assert tb._xaxis.height_max > 42, "the strip deepens for turned names"
print(f"category names: {angle} degrees automatically ({slot:.0f} px each); flat ones thinned to every {flat_nth}")
# numbers: a big font and many ticks leave every 2nd... blank, never overlapping
t2 = w._open_plot(PlotSpec(kind="2D Scatter", x=X, y=Y, color=MP), ALL); drain()
t2.set_element("xaxis", "ticks", 12); t2.set_element("xaxis", "format", "sci"); t2.set_element("xaxis", "tick_size", 16)
settle(t2)
fr, _, lab = t2._xaxis.axis.ticker._get_tick_frac_labels()
fm = t2._label_metrics(t2._el_style["xaxis"], "tick_")
xs = [f * float(t2._view.size[0]) for f, l in zip(fr, lab) if l]
ws = [fm.horizontalAdvance(l) for l in lab if l]
assert len(xs) < len(lab), "some numbers left out"
assert all(b - a >= (wa + wb) / 2 for a, b, wa, wb in zip(xs, xs[1:], ws, ws[1:])), "the rest don't overlap"
t2.set_element("cbar", "num_ticks", 12); t2.set_element("cbar", "num_size", 20)
settle(t2); t2._place_cbar_ticks()
assert t2._cbar_extra and not all(x.visible for x in t2._cbar_extra), "colour bar numbers too"
print("numbers: thinned on axes and the colour bar when they'd overlap")

# --- pop out keeps it all ------------------------------------------------------------------------
w.tabbar.setCurrentIndex(w.stack.indexOf(tl)); app.processEvents()
tl.set_element("title", "align", "left")
w._popout_plot(); app.processEvents(); dt = w._detached[-1]._tab
assert dt.element_values("legend")["place"] == "bottom_left" and dt._legend.parent is dt._view
assert dt.element_values("title")["align"] == "left"
c.shutdown()
print("PLOT ELEMENT LAYOUT CHECKS PASS")
