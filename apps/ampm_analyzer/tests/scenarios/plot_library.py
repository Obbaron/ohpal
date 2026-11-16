"""Plots that outlive the session: a build's own plots reopen with it (live,
with their look and filter; cleared by a rebuild), and the plot library keeps
frozen plots that show the numbers of the build they came from, opened beside
another build's plots or with no build open."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import json, os, shutil, sys, tempfile, time
BUILD = sys.argv[1]
TMP = tempfile.mkdtemp()
import numpy as np
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication, QFileDialog
app = QApplication([])
from ampm_analyzer.shell import controller as cmod, message_dialog, plot_library as pl_lib
from ampm_analyzer.shell.plotspec import PlotSpec
from ampm_analyzer.shell.window import MainWindow

cmod._tell = lambda *a, **k: None
OTHER = os.path.join(TMP, "Second build")
shutil.copytree(BUILD, OTHER)          # a second build (same data, its own cache)
ALL = ("all", None, None)
told = []
message_dialog.tell = lambda parent, title, text, **k: told.append(text)
asked = []
message_dialog.ask = lambda parent, title, text, **k: (asked.append(text), False)[1]

w = MainWindow(); w.resize(1200, 760); w.show(); c, s = w.controller, w.session
def drain(limit=300):
    t0 = time.time()
    while time.time() - t0 < limit:
        app.processEvents()
        if not c._queue and c._current is None and not c._busy:
            for _ in range(30): app.processEvents(); time.sleep(0.003)
            if not c._queue and c._current is None: return
        time.sleep(0.01)
def open_build(path):
    loop = QEventLoop(); h = s.queryReady.connect(lambda *_: loop.quit())
    QTimer.singleShot(240000, loop.quit); c.open_recent(path); loop.exec()
    s.queryReady.disconnect(h); drain()
def labels():
    return [w.tabbar.tabText(i) for i in range(w.tabbar.count())]

open_build(BUILD)
A = s.build_name; cache_a = s.store.cache_dir
cols = list(s.result.df.columns); X, Y = "Demand X", "Demand Y"
MP = next(n for n in cols if "elt" in n and "ool" in n)

# --- a build's own plots: kept with it ------------------------------------------------
assert pl_lib.load_build_plots(cache_a) == []
w._run("filter_add", condition="[layer] > 2"); drain()
sc = w._open_plot(PlotSpec(kind="2D Scatter", x=X, y=Y, color=MP), ALL); drain()
w._remove_filter_at(0); drain(); assert c.filters() == []
sc.set_element("title", "text", "Melt pool map"); sc.set_element("title", "align", "left")
sc.set_element("cbar", "orient", "bottom"); sc.set_marker_size(6)
lv = w._open_plot(PlotSpec(kind="Layer Viewer", x=X, y=Y, color=MP), ("single", 3, 3)); drain()
kd = w._open_plot(PlotSpec(kind="KDE", x=MP, y="density", group_by="part_id"), ALL); drain()
recs = pl_lib.load_build_plots(cache_a)
assert [r["spec"]["kind"] for r in recs] == ["2D Scatter", "Layer Viewer", "KDE"], recs
assert recs[0]["row_filter"] == ["[layer] > 2"], "the plot keeps the filter it was made with"
w._select_widget(kd); w._popout_plot(); drain()
assert len(w._detached) == 1
assert [r["spec"]["kind"] for r in pl_lib.load_build_plots(cache_a)] == ["2D Scatter", "Layer Viewer"], \
    "a floating window isn't the build's tab while the app runs"
print("build plots kept with the build as they open, change and close")

# another build: A's plots close (they're A's), the floating window stays
open_build(OTHER)
B = s.build_name; cache_b = s.store.cache_dir
assert cache_b != cache_a and not w._plot_tabs, labels()
assert len(w._detached) == 1, "floating windows are self-contained"
assert [r["spec"]["kind"] for r in pl_lib.load_build_plots(cache_a)] == ["2D Scatter", "Layer Viewer"]
assert pl_lib.load_build_plots(cache_b) == []
w._detached[0].close(); drain()

# back to A: they reopen, behind the Data tab, with their look
open_build(BUILD)
drain()
tabs = list(w._plot_tabs)
assert [t.spec.kind for t in tabs] == ["2D Scatter", "Layer Viewer"], [t.spec.kind for t in tabs]
r_sc, r_lv = tabs
assert w.stack.currentWidget() is w._data_tab, "reopened plots don't take the screen"
assert r_sc.title == "Melt pool map" and "Melt pool map" in labels()
assert r_sc.element_values("title")["align"] == "left" and r_sc._cbar_orient == "bottom"
assert r_sc.marker_size() == 6 and r_sc.row_filter == ["[layer] > 2"]
assert r_sc._df is not None and r_sc._df.height > 0 and r_sc._df["layer"].min() > 2, "drawn live, with its filter"
assert r_lv.span == ("single", 3, 3) and r_lv._df["layer"].unique().to_list() == [3]
assert "Reopened this build's 2 plots" in w._log._full
# a floating window joins the build's plots when the app closes (reopens as a tab)
w._select_widget(r_lv); app.processEvents(); w._popout_plot(); drain()
kinds = lambda: [r["spec"]["kind"] for r in pl_lib.load_build_plots(cache_a)]
assert kinds() == ["2D Scatter"]
w._save_plots(windows=True); assert kinds() == ["2D Scatter", "Layer Viewer"]
w._dock_plot(w._detached[-1]); drain(); r_lv = w._active_plot
assert r_lv.spec.is_layer_viewer and kinds() == ["2D Scatter", "Layer Viewer"], "docked back: the build's again"
print("reopened with the build: kinds, titles, look, filter, layer")

# --- the plot library: frozen plots ---------------------------------------------------
lib = pl_lib.folder(); assert str(lib).startswith(str(_harness.ROOT)), lib
saves = []
def save_to(name):
    path = os.path.join(str(pl_lib.ensure_folder()), name)
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (saves.append(a[2]) or path, ""))
    return path
w._select_widget(r_sc); app.processEvents()
tips = [a.toolTip() for a in w.toolbar.actions() if a.toolTip()]
assert "Save to plot library" in tips, tips
f_sc = save_to("map")                                  # no suffix typed
w._plot_control(r_sc, "save_library"); drain()
f_sc += pl_lib.SUFFIX
assert os.path.exists(f_sc) and saves[-1].endswith(f"Melt pool map ({A}){pl_lib.SUFFIX}"), saves
info, df = pl_lib.load_frozen(f_sc)
assert info["build"] == A and info["spec"]["kind"] == "2D Scatter" and info["title"] == "Melt pool map"
assert df.height == r_sc._df.height and set(df.columns) <= set(r_sc._df.columns)
assert set(df.columns) == {X, Y, MP, "part_id", "layer"}, df.columns
assert abs(df[MP].sum() - r_sc._df[MP].sum()) < 1e-6 * max(1.0, abs(df[MP].sum()))
assert info["appearance"]["elements"]["cbar"]["orient"] == "bottom"
SUM_A = float(df[MP].sum())
f_lv = save_to("viewer.ampmplot")
w._select_widget(r_lv); app.processEvents()
w._plot_control(r_lv, "save_library"); drain()
info_lv, df_lv = pl_lib.load_frozen(f_lv)
assert sorted(df_lv["layer"].unique().to_list()) == list(r_lv._layers) and info_lv["layers"] == list(r_lv._layers), \
    "a Layer Viewer keeps every layer"
assert len(pl_lib.entries()) == 2 and pl_lib.entries()[0].kind in ("Layer Viewer", "2D Scatter")
# big plots ask first (here: no)
real_big = pl_lib.BIG_BYTES; pl_lib.BIG_BYTES = 10
save_to("big.ampmplot"); w._select_widget(r_sc); app.processEvents()
w._plot_control(r_sc, "save_library"); drain()
assert asked and "Save it?" in asked[-1] and not os.path.exists(os.path.join(str(lib), "big.ampmplot"))
pl_lib.BIG_BYTES = real_big
print("saved to the library: the rows drawn, the look, where it came from; Layer Viewer: every layer")

# --- open it beside another build ------------------------------------------------------
open_build(OTHER)
w._run("derive", name="twice", expr=f"[{MP}] * 2"); drain()
w._show_plot_library(); app.processEvents()
assert w.stack.currentIndex() == 0 and w.backstage.main_stack.currentIndex() == 2
rows = [w.backstage.library.item(i).text() for i in range(w.backstage.library.count())]
assert len(rows) == 2 and any("Melt pool map" in r and f"from {A}" in r for r in rows), rows
i = next(i for i, r in enumerate(rows) if "Melt pool map" in r)
w.backstage.library.setCurrentRow(i); w.backstage._open_selected_plot(); drain()
fz = w._active_plot
assert fz is not None and fz.context["frozen"]["build"] == A
assert f"Melt pool map · {A}" in labels()
assert abs(float(fz._df[MP].sum()) - SUM_A) < 1e-6 * max(1.0, abs(SUM_A)), "the numbers of the build it came from"
assert fz.element_values("title")["align"] == "left" and fz._cbar_orient == "bottom"
w._run("derive", name="thrice", expr=f"[{MP}] * 3"); drain()
assert "thrice" not in fz._df.columns, "a frozen plot doesn't follow the open build"
assert pl_lib.load_build_plots(cache_b) == [], "and it isn't one of this build's plots"
# a frozen Layer Viewer scrubs its own layers
w._open_from_library(f_lv); drain(); fl = w._active_plot
assert fl.spec.is_layer_viewer and fl._df["layer"].unique().to_list() == [3]
fl.step_layer(1); drain(); time.sleep(0.15); drain()
assert fl._df["layer"].unique().to_list() == [4], fl._df["layer"].unique().to_list()
# pop out and dock back: still frozen
w._select_widget(fl); app.processEvents(); w._popout_plot(); drain()
win = w._detached[-1]; assert win._frozen and win._tab._df["layer"].unique().to_list() == [4]
win._tab.step_layer(1); drain(); time.sleep(0.15); drain()
assert win._tab._df["layer"].unique().to_list() == [5]
w._dock_plot(win); drain(); fl2 = w._active_plot
assert fl2.context["frozen"] and fl2._df["layer"].unique().to_list() == [5]
print("opened beside another build: its own numbers and look; frozen layers scrub; pop out / dock")

# switching builds keeps frozen plots open; they never join a build's plots
open_build(BUILD); drain()
assert fz in w._plot_tabs and fl2 in w._plot_tabs
assert [r["spec"]["kind"] for r in pl_lib.load_build_plots(cache_a)] == ["2D Scatter", "Layer Viewer"]

# a damaged file says so
bad = os.path.join(str(lib), "bad.ampmplot"); open(bad, "wb").write(b"not a zip")
n = len(w._plot_tabs); w._open_from_library(bad)
assert len(w._plot_tabs) == n and "can't be opened" in told[-1], told
assert all(e.path != bad for e in pl_lib.entries()), "unreadable files aren't listed"

# --- a rebuild clears the build's plots -------------------------------------------------
w._reset_build_state()
assert pl_lib.load_build_plots(cache_a) == [] and not os.path.exists(os.path.join(cache_a, "plots.json"))
assert fz in w._plot_tabs, "frozen plots stay"
print("rebuild: the build's plots are gone; frozen ones stay")

# --- with no build open --------------------------------------------------------------------
c.shutdown()
w2 = MainWindow(); w2.show(); app.processEvents()
assert w2.session.result is None
w2._open_from_library(f_sc); app.processEvents()
t2 = w2._active_plot
assert t2 is not None and t2._df is not None and abs(float(t2._df[MP].sum()) - SUM_A) < 1e-6 * max(1.0, abs(SUM_A))
assert w2._data_tab is None, "no Data tab without a build"
# the folder is a setting
other_lib = os.path.join(TMP, "team plots"); os.makedirs(other_lib)
pl_lib.set_folder(other_lib); assert pl_lib.entries() == [] and not pl_lib.is_default_folder()
pl_lib.set_folder(None); assert len(pl_lib.entries()) == 2
# closing the app keeps the build's floating windows with it (they reopen as tabs)
w2.controller.shutdown()
print("opened with no build; the library folder is a setting")
print("PLOT LIBRARY CHECKS PASS")
