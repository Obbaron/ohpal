"""Editable plot elements: panel ⇄ plot wiring, defaults, reset, selection,
pop-out / dock, on the real build (no GL needed)."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import sys, time, types
BUILD = sys.argv[1]
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QColorDialog
app = QApplication([])
from ampm_viewer.shell import controller as cmod, plot_elements as pe
from ampm_viewer.shell.plotspec import PlotSpec
from ampm_viewer.shell.window import MainWindow
cmod._tell = lambda *a, **k: None
w = MainWindow(); w.resize(1200, 700); w.show(); c, s = w.controller, w.session
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
cols = list(s.result.df.columns); X, Y = "Demand X", "Demand Y"
assert X in cols and Y in cols, cols
MP = next(n for n in cols if "elt" in n and "ool" in n)
panel = w.panel
ctl = lambda name: panel._el_controls[name][1]

tab = w._open_plot(PlotSpec(kind="2D Scatter", x=X, y=Y, color=MP), ("all", None, None)); drain()
assert tab.element_values("title")["font"] == "Open Sans" and tab.element_values("title")["size"] == 13
assert tab._title_label._text_visual.face == "OpenSans"
assert set(tab._el_style) == {"title", "xaxis", "yaxis", "categories", "cbar", "legend", "data_points"}
assert tab._xaxis.axis.axis_label == X and tab._yaxis.axis.axis_label == Y

# --- a click selects (the panel, if open, follows); double-click opens it -------
w._toggle_sidebar(False); assert not panel.isVisible()
tab.select_element("title")
assert tab.selected_element() == "title" and not panel.isVisible(), "a click doesn't open the panel"
tab.elementActivated.emit("title")
assert panel.isVisible() and panel.element_key() == "title" and panel.el_heading.text() == "Title"
assert panel._plot_stack.currentIndex() == 1 and ctl("text").text() == tab.title
assert set(panel._el_controls) == {"text", "font", "size", "bold", "italic", "color", "align"}
print("double-click opens the editor:", sorted(panel._el_controls))
# panel open: a single click shows the new selection at once, even from the
# plot's own controls
tab.select_element(None); assert panel.element_key() is None and panel._plot_stack.currentIndex() == 0
tab.select_element("yaxis"); assert panel.element_key() == "yaxis" and panel.el_heading.text() == "Y axis"
tab.select_element("title"); assert panel.element_key() == "title"
# a click on the toolbar's empty space deselects
from PyQt6.QtCore import QEvent, QPointF, Qt as _Qt
from PyQt6.QtGui import QMouseEvent
def blank_click(bar):
    p = QPointF(bar.width() - 5, bar.height() / 2)
    QApplication.sendEvent(bar, QMouseEvent(QEvent.Type.MouseButtonPress, p, QPointF(bar.mapToGlobal(p.toPoint())),
                                            _Qt.MouseButton.LeftButton, _Qt.MouseButton.LeftButton, _Qt.KeyboardModifier.NoModifier))
blank_click(w.toolbar)
assert tab.selected_element() is None and panel.element_key() is None and panel.isVisible()
# re-opening the panel shows what is selected
w._toggle_sidebar(False); tab.select_element("xaxis"); w._toggle_sidebar(True)
assert panel.element_key() == "xaxis"
# the Data tab: the toolbar's empty space clears the column selection too
w.tabbar.setCurrentIndex(w.stack.indexOf(w._data_tab)); app.processEvents()
w._data_tab.table.selectColumn(1); assert w._data_tab.selected_columns()
blank_click(w.toolbar); assert w._data_tab.selected_columns() == []
w.tabbar.setCurrentIndex(w.stack.indexOf(tab)); app.processEvents()
tab.select_element("title"); tab.elementActivated.emit("title"); assert panel.element_key() == "title"   # as before
print("open panel follows single clicks; empty toolbar space deselects (plot and grid)")

# --- live edits ----------------------------------------------------------------
tv = tab._title_label._text_visual
ctl("size").setValue(20); assert tab.element_values("title")["size"] == 20 and tv.font_size == 20
ctl("font").setCurrentText("Liberation Serif"); assert tv.face == "LiberationSerif"
ctl("bold").setChecked(True); ctl("italic").setChecked(True); assert tv.bold and tv.italic
QColorDialog.getColor = staticmethod(lambda *a, **k: QColor("#aa2222"))
ctl("color").click(); assert tab.element_values("title")["color"] == "#aa2222" and ctl("color").text() == "#aa2222"
ctl("text").setText("Layer 7 melt pool"); ctl("text").textEdited.emit("Layer 7 melt pool")
assert tab.title == "Layer 7 melt pool" and w.tabbar.tabText(w.stack.indexOf(tab)) == "Layer 7 melt pool"
assert tab._title_label.height_max > 28, "a bigger title needs a taller strip"
print("title edits apply live; the tab follows the title text")

# --- an open editor follows the selection; clicking off closes it -----------------
tab.select_element("xaxis")
assert panel.element_key() == "xaxis" and panel.el_heading.text() == "X axis"
assert ctl("text").text() == "" and ctl("text").placeholderText() == X
assert {"tick_font", "tick_size", "tick_color"} <= set(panel._el_controls)
ctl("text").textEdited.emit("X position (mm)"); assert tab._xaxis.axis.axis_label == "X position (mm)"
ctl("text").textEdited.emit(""); assert tab._xaxis.axis.axis_label == X, "empty text → the column's name"
ctl("tick_size").setValue(12); ctl("size").setValue(14)
ax = tab._xaxis.axis
assert ax._text.font_size == 12 and ax._axis_label_vis.font_size == 14 and tab._xaxis.height_max > 42
ctl("tick_font").setCurrentText("Liberation Mono"); assert ax._text.face == "LiberationMono" and ax._axis_label_vis.face == "OpenSans"
tab.select_element(None)
assert panel.element_key() is None and panel._plot_stack.currentIndex() == 0
print("editor follows the selection; deselecting returns to the plot controls")

# click vs drag on the canvas
ev = lambda x, y: types.SimpleNamespace(pos=(x, y), button=1, buttons=[])
tab._element_at = lambda pos: "yaxis" if pos is not None and pos[0] < 50 else None
tab._on_mouse_press(ev(20, 200)); tab._on_mouse_release(ev(21, 201)); assert tab.selected_element() == "yaxis"
tab._on_mouse_press(ev(20, 200)); tab._on_mouse_release(ev(60, 300)); assert tab.selected_element() == "yaxis", "a drag is not a click"
tab._on_mouse_press(ev(300, 200)); tab._on_mouse_release(ev(300, 200)); assert tab.selected_element() is None
tab._on_double_click(ev(20, 200)); assert panel.element_key() == "yaxis"
panel._close_element(); assert tab.selected_element() is None and panel.element_key() is None
del tab._element_at
print("click selects, drag doesn't, click on the data deselects, back arrow deselects")

# --- a renamed column flows into the automatic axis title ---------------------------
out = w._run("rename", old=X, new="Xpos"); assert out.ok, out
drain()
assert tab.spec.x == "Xpos" and tab._xaxis.axis.axis_label == "Xpos", tab._xaxis.axis.axis_label
w._undo(); drain(); assert tab._xaxis.axis.axis_label == X
w.tabbar.setCurrentIndex(w.stack.indexOf(tab)); app.processEvents()   # a rename shows the Data tab
print("automatic axis titles follow a column rename (and its undo)")

# --- set as default → new plots start from it; reset --------------------------------
tab.elementActivated.emit("title")
panel.el_default_btn.click()
saved = pe.saved_default("title")
assert saved == {"font": "Liberation Serif", "size": 20.0, "bold": True, "italic": True, "color": "#aa2222"}, saved
assert "default for new plots" in w._log._full
tab2 = w._open_plot(PlotSpec(kind="2D Scatter", x=X, y=Y, color=MP), ("all", None, None)); drain()
v2 = tab2.element_values("title")
assert v2["font"] == "Liberation Serif" and v2["size"] == 20 and v2["bold"] and tab2.title != tab.title, v2
assert tab2._title_label._text_visual.face == "LiberationSerif"
assert tab2.element_values("xaxis")["size"] == 9, "only the title's default was saved"
assert panel.element_key() is None, "switching plots leaves the editor"
tab2.elementActivated.emit("title")
ctl("size").setValue(30)
panel.elementReset.emit("title", False)            # Reset ▸ To my default
assert tab2.element_values("title")["size"] == 20 and ctl("size").value() == 20
panel.elementReset.emit("title", True)             # Reset ▸ To the built-in look
b = tab2.element_values("title")
assert (b["font"], b["size"], b["bold"], b["color"]) == ("Open Sans", 13, False, "#2a2f3a") and ctl("size").value() == 13
assert ctl("text").text() == tab2.title, "reset keeps the text"
panel.el_default_btn.click(); assert pe.saved_default("title") == {}, "built-in look as default clears the saved one"
assert tab.element_values("title")["size"] == 20, "existing plots keep their own styling"
print("Set as default → new plots; Reset to my default / built-in; existing plots untouched")

# --- pop out and dock back carry the styling -----------------------------------------
w.tabbar.setCurrentIndex(w.stack.indexOf(tab)); app.processEvents()
before = {k: tab.element_values(k) for k in tab._el_style}
w._popout_plot(); app.processEvents()
win = w._detached[-1]; dt = win._tab
assert {k: dt.element_values(k) for k in dt._el_style} == before
dt.elementActivated.emit("yaxis")
assert not win._panel.isHidden() and win._panel.element_key() == "yaxis"
win._panel._el_controls["size"][1].setValue(15); assert dt.element_values("yaxis")["size"] == 15
win._panel.elementReset.emit("yaxis", True); assert dt.element_values("yaxis")["size"] == 9
win._panel._el_controls["italic"][1].setChecked(True)
n = len(w._plot_tabs); w._dock_plot(win); app.processEvents(); drain()
back = w._plot_tabs[-1]
assert len(w._plot_tabs) == n + 1 and back.element_values("yaxis")["italic"] and back.element_values("title") == before["title"]
print("pop-out and dock-in keep every element's styling; the floating window has its own editor")

# --- 3D + bars expose their own elements -------------------------------------------
t3 = w._open_plot(PlotSpec(kind="3D Scatter", x=X, y=Y, z="Z", color=MP), ("all", None, None)); drain()
assert set(t3._el_style) == {"title", "xaxis3d", "yaxis3d", "zaxis3d", "cbar", "legend", "data_points"}
assert len(t3._axis_labels) == 3 and t3._axis_labels[2].text == "Z" and t3._axis_labels[0].bold
t3.set_element("zaxis3d", "text", "Height"); t3.set_element("zaxis3d", "size", 16)
assert t3._axis_labels[2].text == "Height" and t3._axis_labels[2].font_size == 16
t3.set_dataframe(t3._df); assert t3._axis_labels[2].text == "Height" and t3._axis_labels[2].font_size == 16, "styling survives a re-render"
tb = w._open_plot(PlotSpec(kind="Bar", x="layer", y=MP, agg="mean"), ("all", None, None)); drain()
assert tb._categories and tb.element_auto_text("yaxis") == tb._bar_data.value_name == tb._yaxis.axis.axis_label
tb.set_element("categories", "size", 12); tb.set_element("categories", "bold", True)
cat = tb._xaxis.axis._text; assert cat.font_size == 12 and cat.bold, "the names are the x axis labels"
tb.set_dataframe(tb._df); assert cat.font_size == 12 and cat.bold
tb.elementActivated.emit("cbar"); assert panel.el_heading.text() == "Colour bar" and ctl("text").placeholderText() == tb._cbar_auto
ctl("num_size").setValue(9); assert all(t.font_size == 9 for t in tb._cbar.ticks)
print("3D axis labels, category labels and the colour bar are editable and survive re-renders")

# bad saved defaults can't break a plot
from ampm_viewer.shell.settings import app_settings
app_settings().setValue("plot_style/title", '{"font": "Comic Sans", "size": "huge", "bold": 1, "text": "x", "nope": 3}')
assert pe.default_style("title") == {**pe.builtin_style("title"), "bold": True}
app_settings().setValue("plot_style/title", "not json"); assert pe.saved_default("title") == {}
c.shutdown()
print("ALL ELEMENT CHECKS PASS")
