"""Contextual plot controls: the toolbar, side panel and legend follow the plot;
the nine view options work; custom views can inherit controls."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import sys, time
BUILD = sys.argv[1]
import numpy as np
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication, QToolButton
app = QApplication([])
from ampm_viewer.shell import controller as cmod, icons, plotcontrols as PC
from ampm_viewer.shell.plotspec import (PLOT_KINDS, BAR, CONTOUR, COV_SUMMARY, HISTOGRAM, KDE, KDIST,
                                          LAYER_VIEWER, SCATTER_2D, SCATTER_3D, SINGLE_LAYER, VIOLIN,
                                          PlotSpec, default_spec)
from ampm_viewer.shell.window import MainWindow

# --- the control model ---------------------------------------------------------------
for kind in PLOT_KINDS:
    cs = PC.controls_for(kind)
    keys = [c.key for c in cs]
    assert keys[0] == "reset_view" and keys[-2:] == ["screenshot", "save_library"], (kind, keys)
    assert len(set(keys)) == len(keys), keys
    groups = [PC.GROUPS.index(c.group) for c in cs]
    assert groups == sorted(groups), (kind, keys)       # grouped, in order
    for c in cs:
        assert not icons.ui(c.icon, "#000").isNull(), c.icon
        assert c.kind in ("toggle", "action", "choice", "menu")
        assert (c.kind in ("choice", "menu")) == bool(c.choices), c
        assert "—" not in c.label and "–" not in c.label
assert "camera" in [c.key for c in PC.controls_for(SCATTER_3D)]
assert {"layer_prev", "layer_next", "equal_axes"} <= {c.key for c in PC.controls_for(LAYER_VIEWER)}
# a custom view: inherits its base view's options, adds its own
mine = PC.Control("smooth", "Smooth", "kde_fill", "toggle", "options")
cv = [c.key for c in PC.controls_for("My melt-pool view", base=KDE, extra=(mine,))]
assert cv.index("fill") < cv.index("smooth") < cv.index("screenshot") and "bandwidth" in cv, cv
assert [c.key for c in PC.controls_for("Unknown view")] == [c.key for c in PC.COMMON]
print("control model: every kind grouped in order, icons resolve, custom views inherit + extend")

# --- in the app ----------------------------------------------------------------------
cmod._tell = lambda *a, **k: None
w = MainWindow(); w.resize(1300, 800); w.show(); c, s = w.controller, w.session
def wait_ready(kick):
    loop = QEventLoop(); h = s.queryReady.connect(lambda *_: loop.quit())
    QTimer.singleShot(240000, loop.quit); kick(); loop.exec(); s.queryReady.disconnect(h)
def drain():
    t0 = time.time()
    while time.time() - t0 < 300:
        app.processEvents()
        if not c._queue and c._current is None and not c._busy:
            for _ in range(40): app.processEvents(); time.sleep(0.005)
            if not c._queue and c._current is None: return
        time.sleep(0.02)
def tips(tb):
    """Tooltips across the toolbar: plain actions and menu buttons, in order."""
    out = []
    for a in tb.actions():
        wdg = tb.widgetForAction(a)
        t = wdg.toolTip() if isinstance(wdg, QToolButton) and wdg.menu() else a.toolTip()
        if t:
            out.append(t)
    return out
def button(tb, tip):
    for a in tb.actions():
        wdg = tb.widgetForAction(a)
        if isinstance(wdg, QToolButton) and wdg.menu() and wdg.toolTip() == tip:
            return wdg
        if a.toolTip() == tip:
            return a
    raise AssertionError(f"{tip!r} not in {tips(tb)}")
def menu_pick(tb, tip, text):
    m = button(tb, tip).menu()
    act = next(a for a in m.actions() if a.text() == text)
    act.trigger(); drain()
    return act
def show(tab):
    w.tabbar.setCurrentIndex(w.stack.indexOf(tab)); drain()

wait_ready(lambda: c.open_recent(BUILD)); drain()
cols = list(s.result.df.columns); MP = next(n for n in cols if "elt" in n and "ool" in n)
ALL = ("all", None, None)

# 2D scatter coloured by a number: colour bar -> Legend; no BBox; equal axes on
t2 = w._open_plot(PlotSpec(kind=SCATTER_2D, x="Demand X", y="Demand Y", color=MP), ALL); drain()
tt = tips(w.toolbar); print("2D scatter:", tt)
assert tt[:3] == ["Show/hide panel", "Reset view", "Equal axes (1:1)"], tt
assert "BBox" not in tt and "Legend" in tt and "Screenshot" in tt and tt[-1] == "Pop out"
assert t2._view.camera.aspect == 1 and button(w.toolbar, "Equal axes (1:1)").isChecked()
button(w.toolbar, "Equal axes (1:1)").trigger(); drain()
assert t2._view.camera.aspect is None and t2.control_value("equal_axes") is False
button(w.toolbar, "Equal axes (1:1)").trigger(); drain(); assert t2._view.camera.aspect == 1
button(w.toolbar, "Legend").trigger(); drain()
assert not t2._cbar.visible and t2.control_value("legend") is False
button(w.toolbar, "Legend").trigger(); drain(); assert t2._cbar.visible
ps = t2.panel_state(); w.panel.sync_plot(ps)
assert ps["has_points"] and not w.panel.points_box.isHidden() and not w.panel.colour_box.isHidden()
assert not w.panel.min_slider.isHidden() and w.panel.plot_note.isHidden()

# 2D scatter in one colour: no legend at all
t1 = w._open_plot(PlotSpec(kind=SCATTER_2D, x="Demand X", y="Demand Y", color=None), ALL); drain()
assert "Legend" not in tips(w.toolbar) and not t1._has_legend
assert t1._cbar is None or not t1._cbar.visible
w.panel.sync_plot(t1.panel_state())
assert w.panel.colour_box.isHidden() and not w.panel.points_box.isHidden()

# 2D scatter coloured by text (20 parts): a legend of the categories, map-coloured
tc = w._open_plot(PlotSpec(kind=SCATTER_2D, x="Demand X", y="Demand Y", color="part_id"), ALL); drain()
assert "Legend" in tips(w.toolbar) and tc._has_legend and tc._legend.visible
assert tc._cbar is None or not tc._cbar.visible, "a legend box, not a colour bar"
names = tc._legend_items[0]
assert names[:3] == ["Part(1)", "Part(2)", "Part(3)"], names          # in natural order
assert tc._legend_auto == "part_id"
ps = tc.panel_state(); assert ps["map_only"] and not ps["has_color"]
w.panel.sync_plot(ps)
assert not w.panel.colour_box.isHidden() and w.panel.min_slider.isHidden()
before = tc._last_colors.copy(); tc.set_colormap("viridis"); drain()
assert not np.allclose(before, tc._last_colors), "the map recolours many categories"
print("2D scatters: legend only when there is one (colour bar or categories); equal axes lock")
def done(*tabs):
    """Close plots this scenario has finished with: each holds its rows, and
    several scenarios run at once (keep the peak memory down)."""
    import gc
    for t in tabs: w._close_plot(t)
    drain(); gc.collect()
done(tc)

# 3D: BBox + 3D view presets
t3 = w._open_plot(PlotSpec(kind=SCATTER_3D, x="Demand X", y="Demand Y", z="Z", color=MP), ALL); drain()
tt = tips(w.toolbar); print("3D scatter:", tt)
assert "BBox" in tt and "3D view" in tt and "Equal axes (1:1)" not in tt
m = button(w.toolbar, "3D view").menu()
assert [a.text() for a in m.actions()] == ["Top", "Front", "Side", "Iso"]
assert not any(a.isCheckable() for a in m.actions())       # one-shot, no tick
for text, (el, az) in (("Top", (90, 0)), ("Front", (0, 0)), ("Side", (0, 90)), ("Iso", (30, 45))):
    menu_pick(w.toolbar, "3D view", text)
    assert (t3._view.camera.elevation, t3._view.camera.azimuth) == (el, az), text

# Layer Viewer: prev / next step the scrubber (and re-query)
tl = w._open_plot(default_spec(LAYER_VIEWER, cols, s.renames), ("single", s.store.layers[3], s.store.layers[3])); drain()
tt = tips(w.toolbar); print("Layer Viewer:", tt)
assert tt.index("Previous layer") < tt.index("Next layer") < tt.index("Axes")
seen = []; tl.layerChanged.connect(seen.append)
i0 = tl._slider.value()
button(w.toolbar, "Next layer").trigger(); time.sleep(0.15); drain()
assert tl._slider.value() == i0 + 1 and seen and seen[-1] == tl._layers[i0 + 1], (seen, i0)
button(w.toolbar, "Previous layer").trigger(); button(w.toolbar, "Previous layer").trigger(); time.sleep(0.15); drain()
assert tl._slider.value() == i0 - 1
tl._slider.setValue(0); tl.step_layer(-1); assert tl._slider.value() == 0      # clamps

# Single layer: equal axes, no layer stepping
tsl = w._open_plot(default_spec(SINGLE_LAYER, cols, s.renames), ("single", s.store.layers[0], s.store.layers[0])); drain()
tt = tips(w.toolbar); assert "Equal axes (1:1)" in tt and "Next layer" not in tt
print("3D presets set the camera; layer step buttons move the scrubber; single layer has no stepping")
done(tl, tsl)

# Histogram: bins (current ticked), no Points panel
th = w._open_plot(PlotSpec(kind=HISTOGRAM, x=MP, y="count", bins=30), ALL); drain()
tt = tips(w.toolbar); print("Histogram:", tt)
assert "Bins" in tt and "Equal axes (1:1)" not in tt and "BBox" not in tt
m = button(w.toolbar, "Bins").menu()
assert [a.text() for a in m.actions()] == ["10", "20", "30", "50", "100"]
assert [a.text() for a in m.actions() if a.isChecked()] == ["30"]
menu_pick(w.toolbar, "Bins", "50")
assert th.spec.bins == 50 and th._bar_data.n == 50
assert [a.text() for a in button(w.toolbar, "Bins").menu().actions() if a.isChecked()] == ["50"]
th.set_control("bins", 37); drain()       # an off-list count shows up in the menu
assert "37" in [a.text() for a in button(w.toolbar, "Bins").menu().actions()]
w.panel.sync_plot(th.panel_state())
assert w.panel.points_box.isHidden() and w.panel.selected_box.isHidden() and not w.panel.colour_box.isHidden()

# Bar + CoV: sort by name / value
tb = w._open_plot(default_spec(BAR, cols, s.renames), ALL); drain()
by_name = list(tb._bar_data.labels)
assert "Sort bars" in tips(w.toolbar)
menu_pick(w.toolbar, "Sort bars", "By value")
h = tb._bar_data.heights
assert tb.spec.sort == "value" and np.all(np.diff(h[np.isfinite(h)]) <= 0), h
assert sorted(tb._bar_data.labels) == sorted(by_name) and tb._bar_data.labels != by_name
menu_pick(w.toolbar, "Sort bars", "By name"); assert list(tb._bar_data.labels) == by_name
tv_ = w._open_plot(default_spec(COV_SUMMARY, cols, s.renames), ALL); drain()
assert "Sort bars" in tips(w.toolbar)
tv_.set_control("sort", "value"); drain()
h = tv_._bar_data.heights; assert np.all(np.diff(h[np.isfinite(h)]) <= 0)
print("histogram bins re-bin (off-list counts listed); bar and CoV sort by value / name")
done(tv_)

# Violin: quartile box + bandwidth
tvi = w._open_plot(PlotSpec(kind=VIOLIN, x="part_id", y=MP), ALL); drain()
tt = tips(w.toolbar); print("Violin:", tt)
assert "Quartile box and median" in tt and "Bandwidth" in tt and "Legend" in tt
button(w.toolbar, "Quartile box and median").trigger(); drain()
assert tvi.spec.show_box is False and tvi._violin_marks.parent is None
button(w.toolbar, "Quartile box and median").trigger(); drain()
assert tvi._violin_marks.parent is not None
old = tvi._dist_data; menu_pick(w.toolbar, "Bandwidth", "Silverman")
assert tvi.spec.bandwidth == "silverman" and tvi._dist_data is not old
w.panel.sync_plot(tvi.panel_state()); assert w.panel.points_box.isHidden()

# KDE: fill + bandwidth
tk = w._open_plot(PlotSpec(kind=KDE, x=MP, y="density", group_by="part_id"), ALL); drain()
tt = tips(w.toolbar); print("KDE:", tt)
assert "Fill under curves" in tt and "Bandwidth" in tt and "Legend" in tt
assert tk._curve_fill.parent is not None
button(w.toolbar, "Fill under curves").trigger(); drain()
assert tk.spec.fill is False and tk._curve_fill.parent is None and len(tk._curve_lines) == 20
bw0 = tk._dist_data.bandwidths if hasattr(tk._dist_data, "bandwidths") else None
menu_pick(w.toolbar, "Bandwidth", "Silverman"); assert tk.spec.bandwidth == "silverman"
assert [a.text() for a in button(w.toolbar, "Bandwidth").menu().actions() if a.isChecked()] == ["Silverman"]
# one KDE curve: no legend, so no Legend button
tk1 = w._open_plot(PlotSpec(kind=KDE, x=MP, y="density", group_by=None), ALL); drain()
assert "Legend" not in tips(w.toolbar) and not tk1._has_legend
print("violin box + bandwidth; KDE fill + bandwidth; one KDE curve has no Legend")
done(tvi, tk1)

# Contour: measured points + level lines
tco = w._open_plot(default_spec(CONTOUR, cols, s.renames), ALL); drain()
tt = tips(w.toolbar); print("Contour:", tt)
assert "Measured points" in tt and ("Level lines" in tt) == tco._contour_lines_ok
button(w.toolbar, "Measured points").trigger(); drain()
assert tco.spec.show_points is False and not tco._contour_pts.visible
if tco._contour_lines_ok:
    button(w.toolbar, "Level lines").trigger(); drain()
    assert tco.spec.show_lines is False and not tco._contour_lines.visible
    tco.set_control("show_lines", True); drain(); assert tco._contour_lines.visible
w.panel.sync_plot(tco.panel_state()); assert w.panel.points_box.isHidden()

# K-distance: the eps line; no legend, no colour -> the panel's note
td = w._open_plot(default_spec(KDIST, cols, s.renames, dbscan=c.dbscan_params()), ALL); drain()
tt = tips(w.toolbar); print("K-distance:", tt)
assert "eps guide line" in tt and "Legend" not in tt and "BBox" not in tt
button(w.toolbar, "eps guide line").trigger(); drain()
assert td.spec.show_ref is False and td._ref_line.parent is None and td._ref_label.parent is None
button(w.toolbar, "eps guide line").trigger(); drain(); assert td._ref_line.parent is not None
w.panel.sync_plot(td.panel_state())
assert w.panel.points_box.isHidden() and w.panel.colour_box.isHidden() and not w.panel.plot_note.isHidden()
print("contour points + lines; k-distance eps line; empty panel explains itself")
done(tco, td)

# toolbar options never change the macro step that made the plot
spec_before = tb.spec
tb.set_control("sort", "value"); assert tb.spec is not spec_before and spec_before.sort == "name"

# the toolbar follows the active plot, and the controls set changing rebuilds it
show(t3); assert "BBox" in tips(w.toolbar)
show(th); assert "BBox" not in tips(w.toolbar) and "Bins" in tips(w.toolbar)
fired = []; t1.controlsChanged.connect(lambda: fired.append(1))
show(t1); assert "Legend" not in tips(w.toolbar)
t1.spec = PlotSpec(kind=SCATTER_2D, x="Demand X", y="Demand Y", color=MP)
w._query_plot(t1); drain()   # a plot holds only its own columns: a new colour is queried
assert fired and "Legend" in tips(w.toolbar), "a legend appearing adds the Legend button"
print("toolbar rebuilds on tab switch and when a plot's controls change")

# the floating window shows the same controls, and keeps equal axes / options
show(tk); w._popout_plot(); drain(); win = w._detached[-1]
ft = tips(win._toolbar); print("floating KDE:", ft)
assert "Fill under curves" in ft and "Dock in" in ft and "Pop out" not in ft
assert not button(win._toolbar, "Fill under curves").isChecked(), "fill stays off in the floating copy"
button(win._toolbar, "Fill under curves").trigger(); drain()
assert win._tab._curve_fill.parent is not None
show(t2); t2.set_equal_axes(False); w._popout_plot(); drain(); win2 = w._detached[-1]
assert win2._tab._view.camera.aspect is None and not button(win2._toolbar, "Equal axes (1:1)").isChecked()
c.shutdown()
print("CONTROLS CHECKS PASS")
