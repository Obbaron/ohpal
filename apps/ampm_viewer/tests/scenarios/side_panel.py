"""The side panel's cards. On the Data tab with no column selected it shows
the whole grid (rows, columns, layer, filters, sig figs for every decimal
column, which columns show); with a column, that column (a histogram and
summary numbers, its sig figs). On a plot: points, the colormap gallery and
the colour range bar; an element's editor puts font and size on one row and
the bold / italic toggles beside the alignment."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import sys, time
BUILD = sys.argv[1]
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from ampm_viewer.shell import controller as cmod
from ampm_viewer.shell.panel_widgets import Card, ChoiceButtons, CmapGallery, Segmented
from ampm_viewer.shell.plotspec import PlotSpec
from ampm_viewer.shell.window import MainWindow

cmod._tell = lambda *a, **k: None
w = MainWindow(); w.resize(1300, 800); w.show(); c, s = w.controller, w.session
p = w.panel
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
def tiles(grid):
    return {t.name.text(): t.value.text() for t in grid.tiles if not t.isHidden()}

wait_ready(lambda: c.open_recent(BUILD)); drain()
dt = w._data_tab
cols = list(s.result.df.columns)
MP = next(n for n in cols if "elt" in n and "ool" in n)
w.tabbar.setCurrentIndex(w.stack.indexOf(dt)); drain()

# -- nothing selected: the whole grid --------------------------------------
dt.clear_selection(); w._toggle_sidebar(True); drain()
assert p.isVisible() and p.showing_grid()
t = tiles(p.grid_tiles)
total = s.result.total_rows
assert t["Rows"] == f"{total:,}" and t["Filters"] == "None", t
assert t["Layer"] == f"{s.current_layer} of {len(c.available_layers())}", t
hidden = dt.hidden_columns()
listed = [r.property("column") for r in p._column_rows()]
assert set(listed) == set(cols), listed
assert p.columns_count.text() == f"{len(cols) - len(hidden)} of {len(cols)} shown"
assert p.grid_sig.value() == 4 and not p.grid_display_card.isHidden()
print("grid page:", t)

# Columns: the list hides and shows them (undoably, like the toolbar menu).
visible = next(n for n, _k, v in dt.grid_columns() if v and n != MP)
row = next(r for r in p._column_rows() if r.property("column") == visible)
from PyQt6.QtWidgets import QCheckBox
row.findChild(QCheckBox).setChecked(False); drain()
assert visible in dt.hidden_columns()
assert p.columns_count.text() == f"{len(cols) - len(hidden) - 1} of {len(cols)} shown"
w._undo(); drain()
assert visible not in dt.hidden_columns()
p.column_search.setText("melt pool")
shown_rows = [r.property("column") for r in p._column_rows() if not r.isHidden()]
assert shown_rows and all("melt pool" in n.lower() for n in shown_rows), shown_rows
p.column_search.clear()
p.btn_show_all.click(); drain()
assert not dt.hidden_columns() and not p.btn_show_all.isEnabled()
print("columns: hide / undo / find / show all")

# Sig figs for every decimal column.
p.grid_sig.setValue(6)
floats = [n for n, k, _v in dt.grid_columns() if k == "float"]
assert floats and all(dt.model.sigfigs(n) == 6 for n in floats)
dt.set_column_sigfigs(floats[0], 3); w._refresh_grid_panel()
assert "differ" in p.grid_sig_note.text()
p.grid_sig.setValue(4)
print("sig figs: all decimal columns at once")

# Filters: listed, removable, clearable.
w._run("filter_add", condition=f"[{MP}] > 300"); drain()
assert tiles(p.grid_tiles)["Filters"] == "1" and p._filter_list.count() == 1
t = tiles(p.grid_tiles)
assert t[f"Rows of {total:,}"] == f"{s.result.df.height:,}", t
assert p.btn_clear_filters.isEnabled() and p.filters_empty.isHidden()
w._run("filter_add", condition=f"[{MP}] < 400"); drain()
assert p._filter_list.count() == 2
p.filterRemoveRequested.emit(0); drain()
assert c.filters() == [f"[{MP}] < 400"] and p._filter_list.count() == 1
p.btn_clear_filters.click(); drain()
assert c.filters() == [] and not p.filters_empty.isHidden()
assert tiles(p.grid_tiles)["Rows"] == f"{total:,}"
print("filters: listed, removed one, cleared")

# -- one column ------------------------------------------------------------
p.columnPicked.emit(MP); drain()
assert not p.showing_grid() and dt.selected_columns() == [MP]
t = tiles(p.col_tiles)
assert set(t) == {"Rows", "Empty", "Min", "Max", "Mean", "Std dev"}, t
ser = s.result.df[MP]
assert t["Min"] == f"{ser.min():.4g}" and t["Max"] == f"{ser.max():.4g}", t
assert not p.col_hist.isHidden() and sum(p.col_hist._counts) == ser.drop_nulls().len()
assert p.col_type.text() == str(ser.dtype) and not p.col_display_card.isHidden()
p.col_sig.setValue(6)
assert dt.model.sigfigs(MP) == 6 and p.col_sig_preview.text().startswith("Shows as")
assert f"{ser.min():.6g}" in p.col_sig_preview.text()
p.col_sig.setValue(4)
w._open_column_panel("part_id"); drain()
t = tiles(p.col_tiles)
assert set(t) == {"Rows", "Empty", "Distinct"} and p.col_hist.isHidden(), t
assert p.col_display_card.isHidden() and "(" not in p.col_type.text()
# Back: the whole grid, the selection gone.
p.columnClosed.emit(); drain()
assert p.showing_grid() and dt.selected_columns() == []
print("column page: histogram, stats, sig figs preview; back to the grid")

# -- a plot ----------------------------------------------------------------
tab = w._open_plot(PlotSpec(kind="3D Scatter", x="Demand X", y="Demand Y", z="Z", color=MP),
                   ("all", None, None)); drain()
p.sync_plot(tab.panel_state())
assert isinstance(p.map_combo, CmapGallery) and isinstance(p.marker_combo, ChoiceButtons)
assert p.colour_by.text() == f"By {MP}"
p.range_bar.set_low(20); p.range_bar.set_high(60); drain()
assert tab.panel_state()["cmin"] == 20 and tab.panel_state()["cmax"] == 60
fmin, fmax = tab.panel_state()["full_range"]
assert p.range_bar._labels[0] == f"{fmin + (fmax - fmin) * 0.2:.4g}"
assert p._range_row.value.text() == "20% to 60%"
p.map_combo.setCurrentIndex(p.map_combo.findText("viridis")); drain()
assert tab.cmap == "viridis" and p.range_bar._cmap == "viridis"
p.marker_combo.setCurrentIndex(p.marker_combo.findText("ring")); drain()
assert tab.panel_state()["symbol"] == "ring"
p.size_slider.setValue(9); assert p._size_row.value.text() == "9 px"
print("plot: marker buttons, colormap gallery, range bar with values")

# The element editor: cards, font + size on a row, B / I beside alignment.
t2 = w._open_plot(PlotSpec(kind="2D Scatter", x="Demand X", y="Demand Y", color=MP),
                  ("all", None, None)); drain()
p.edit_element(t2, "title"); drain()
cards = [cd for cd in p._el_form_host.findChildren(Card) if not cd.isHidden()]
assert [cd.title() for cd in cards] == ["TEXT"], [cd.title() for cd in cards]
font, size = p._el_controls["font"][1], p._el_controls["size"][1]
assert font.parentWidget() is size.parentWidget(), "font and size share a row"
align = p._el_controls["align"][1]
bold = p._el_controls["bold"][1]
assert isinstance(align, ChoiceButtons) and isinstance(bold.parentWidget(), Segmented)
assert align.parentWidget() is bold.parentWidget().parentWidget(), "B / I beside the alignment"
assert [align.itemData(i) for i in range(align.count())] == ["left", "center", "right"]
align.setCurrentIndex(align.findData("left")); drain()
assert t2.element_values("title")["align"] == "left"
p.edit_element(t2, "xaxis"); drain()
titles = [cd.title() for cd in p._el_form_host.findChildren(Card) if not cd.isHidden()]
assert titles[:4] == ["AXIS TITLE", "TICK LABELS", "SCALE", "TICKS"], titles
print("element editor: cards per group, joined rows")

# Every card fits: the panel is as wide as the widest page or element editor
# needs (with room for a scroll bar), so nothing is cut off on the right.
from ampm_viewer.shell import plot_elements as pe
assert p.minimumWidth() >= 260 and p.width() >= p.minimumWidth()
for key, element in pe.ELEMENTS.items():
    p.show_element(element, {}); drain()
    area = p._plot_stack.currentWidget()
    assert area.widget().width() <= area.viewport().width(), key
    assert not area.horizontalScrollBar().isVisible(), key
p.edit_element(t2, "title"); drain()
print("every element editor fits the panel's width")

# A theme switch re-tints the panel without errors.
w._set_theme_choice("dark"); drain(); w._set_theme_choice("light"); drain()
print("ALL OK")
c.shutdown()
