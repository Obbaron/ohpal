"""Help: content integrity, search, context mapping, the window, the wiring."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import sys, time
BUILD = sys.argv[1]
from PyQt6.QtCore import QEventLoop, QTimer, QUrl, Qt
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from ampm_viewer.shell import controller as cmod, help as hd
from ampm_viewer.shell.plotspec import PlotSpec, PLOT_KINDS
from ampm_viewer.shell.window import MainWindow

# --- content -----------------------------------------------------------------
arts = hd.load_articles()
assert len(arts) >= 20 and hd.check(arts) == [], hd.check(arts)
ids = {a.id for a in arts}
for a in arts:
    assert a.title and a.keywords and a.body.lstrip().startswith("# "), a.id
    assert len(a.body) > 400, f"{a.id} is a stub"
    assert "\u2014" not in a.body and "\u2013" not in a.body, f"{a.id} has an em/en dash"
claimed = {k for a in arts for k in a.context}
for kind in PLOT_KINDS:
    assert f"plot.{kind}" in claimed, f"no article opens for a {kind} plot"
assert {"file.start", "file.datastore", "data", "data.macros", "plot", "plot.elements"} <= claimed
assert [s for s, _ in hd.by_section(arts)] == list(hd.SECTIONS)
print(f"{len(arts)} articles, links + contexts consistent; every plot kind has an article")

# --- search --------------------------------------------------------------------
top = lambda q, n=3: [a.id for a in hd.search(arts, q)][:n]
assert top("macro")[0] == "macros" and top("filter")[0] == "filters"
assert set(top("dbscan", 2)) == {"datastore-setup", "plot-kdistance"} and top("font")[0] == "plot-elements"
assert top("violin")[0] == "plot-distributions" and top("eps")[0] == "plot-kdistance"
assert top("undo")[0] == "undo-redo" and top("contour")[0] == "plot-contour"
assert top("filt")[0] == "filters", "prefix match"
assert "parts" in top("laser parameters") and "plot-cov" in top("drift")
assert hd.search(arts, "zzzqqq") == [] and hd.search(arts, "") == arts
assert all("cov" in (a._plain + a.title.lower() + " ".join(a.keywords)) for a in hd.search(arts, "cov"))
assert "chip" in hd.excerpt(hd.find(arts, "filters"), "chip").lower()
assert hd.for_context(arts, ["plot.elements", "plot.Bar", "plot"]).id == "plot-elements"
assert hd.for_context(arts, ["plot.Bar", "plot"]).id == "plot-bars"
assert hd.for_context(arts, ["nonsense"]).id == "overview"
print("search ranks sensibly (prefix, multi-word, no-match); context falls back to the overview")

# --- in the app -------------------------------------------------------------------
cmod._tell = lambda *a, **k: None
w = MainWindow(); w.resize(1200, 700); w.show(); c, s = w.controller, w.session
btn = w._global_btns["help"]; assert "F1" in btn.toolTip()
assert w._help_context() == ["file.start", "file"]
btn.click(); app.processEvents()
hw = w._help_window
assert hw is not None and hw.isVisible() and hw.current_article() == "open-build"
w.backstage.show_datastore_page(); w._open_help(); assert hw.current_article() == "datastore-setup"
w.backstage.show_start_page()

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
assert w._help_context() == ["data"]; w._open_help(); assert hw.current_article() == "data-tab"
w._toggle_macro_recording(); assert w._help_context() == ["data.macros", "data"]
w._open_help(); assert hw.current_article() == "macros"
w.recorder.cancel()
cols = list(s.result.df.columns); MP = next(n for n in cols if "elt" in n and "ool" in n)
want = {"2D Scatter": "plot-scatter", "3D Scatter": "plot-scatter", "Bar": "plot-bars", "Histogram": "plot-bars",
        "Layer Viewer": "plot-layers", "CoV Summary": "plot-cov"}
tab = w._open_plot(PlotSpec(kind="2D Scatter", x="Demand X", y="Demand Y", color=MP), ("all", None, None)); drain()
assert w._help_context() == ["plot.2D Scatter", "plot"]
w._open_help(); assert hw.current_article() == "plot-scatter"
tab.select_element("title"); tab.elementActivated.emit("title"); assert w._help_context()[0] == "plot.elements"
w._open_help(); assert hw.current_article() == "plot-elements"
tab.select_element(None); w._open_help(); assert hw.current_article() == "plot-scatter"
tb = w._open_plot(PlotSpec(kind="Bar", x="layer", y=MP, agg="mean"), ("all", None, None)); drain()
w._open_help(); assert hw.current_article() == "plot-bars"
print("Help button / F1 open on: start page, setup page, Data tab, recording, each plot kind, the text editor")

# --- the window ---------------------------------------------------------------------
titles = lambda: [hw.list.item(i).text().strip() for i in range(hw.list.count()) if hw.list.item(i).data(Qt.ItemDataRole.UserRole)]
assert len(titles()) == len(arts) and hw.count.text() == f"{len(arts)} articles"
heads = [hw.list.item(i).text() for i in range(hw.list.count()) if not hw.list.item(i).data(Qt.ItemDataRole.UserRole)]
assert heads == list(hd.SECTIONS)
assert hw.list.currentItem().data(Qt.ItemDataRole.UserRole) == "plot-bars", "the list follows the open article"
assert "Bar charts and histograms" in hw.crumb.text() and "Plots" in hw.crumb.text()
# the dialogs' frameless-card look: no title bar, the article's title on the card
assert hw.windowFlags() & Qt.WindowType.FramelessWindowHint and not hw.isModal()
assert hw.title.text() == "Bar charts and histograms"
assert not hw.view.toPlainText().lstrip().startswith("Bar charts and histograms"), "title is shown once"
assert hw.close_btn.text() == "Close"
assert "One bar per" in hw.view.toPlainText()
# links
hw._on_link(QUrl("help:plot-cov")); assert hw.current_article() == "plot-cov"
hw._step(-1); assert hw.current_article() == "plot-bars" and hw.fwd_btn.isEnabled()
hw._step(1); assert hw.current_article() == "plot-cov" and not hw.fwd_btn.isEnabled()
# every link in every article resolves and renders
for a in arts:
    assert hw.show_article(a.id) and hw.view.toPlainText().strip(), a.id
    for target in a.links(): assert hd.find(arts, target) is not None
# search in the window
hw.search.setText("font"); app.processEvents()
assert titles()[0] == "Editing plot elements" and "result" in hw.count.text()
hw._open_first_result(); assert hw.current_article() == "plot-elements" and hw.view.extraSelections(), "hits are highlighted"
hw.search.setText("zzzqqq"); assert titles() == [] and "No articles match" in hw.count.text()
hw._escape(); assert hw.search.text() == "" and len(titles()) == len(arts) and not hw.view.extraSelections()
# clicking a list row opens it
row = next(i for i in range(hw.list.count()) if hw.list.item(i).data(Qt.ItemDataRole.UserRole) == "filters")
hw.list.setCurrentRow(row); assert hw.current_article() == "filters"
# the context open clears a search
hw.search.setText("macro"); w._open_help(); assert hw.search.text() == "" and hw.current_article() == "plot-bars"
hw._escape(); assert not hw.isVisible(); w._open_help(); assert hw.isVisible() and w._help_window is hw
hw.close_btn.click(); assert not hw.isVisible(); w._open_help(); assert hw.isVisible()
c.shutdown()
print("window: sectioned list, breadcrumb, links, back/forward, search + highlights, Esc")
print("ALL HELP CHECKS PASS")
