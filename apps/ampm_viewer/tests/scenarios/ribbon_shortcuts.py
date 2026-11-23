"""The toolbar is a ribbon: big icons in named groups (a name under each, and
no Deselect button), and the keyboard shortcuts press its buttons: Ctrl+B the
side panel, Alt+Down/Up the layer, Ctrl+F/F2/Ctrl+E/Ctrl+N the Data tab's,
Ctrl+0 and Ctrl+Shift+S a plot's, Ctrl+Tab/Ctrl+PgDown the tabs. A pop-out
plot window has the plot ones too. Esc in the grid clears its selection."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import os, sys, time
BUILD = sys.argv[1]
from PyQt6.QtCore import QEventLoop, QTimer, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QToolButton
app = QApplication([])
from ampm_viewer.shell import controller as cmod, shortcuts, toolbars
from ampm_viewer.shell.plotspec import PlotSpec
from ampm_viewer.shell.window import MainWindow
cmod._tell = lambda *a, **k: None
w = MainWindow(); w.resize(1400, 800); w.show(); w.activateWindow()
c, s = w.controller, w.session
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
C, SH, ALT = (Qt.KeyboardModifier.ControlModifier, Qt.KeyboardModifier.ShiftModifier,
              Qt.KeyboardModifier.AltModifier)
def key(k, mods=Qt.KeyboardModifier.NoModifier, target=None):
    QTest.keyClick(target or w, k, mods); app.processEvents()

# The Data ribbon: its groups, named under them, wide enough for their names.
tb = w.toolbar
assert isinstance(tb, toolbars.Ribbon)
groups = [n for n, _ in tb.group_rects()]
want = ["View", "Columns", "Filters", "Clusters", "Plots", "Export", "Macros"]
assert [g for g in groups if g != "Parts"] == want, groups
fm = tb._captions.fontMetrics()
for name, rect in tb.group_rects():
    assert rect.width() + 8 >= fm.horizontalAdvance(name), (name, rect.width())
assert tb.iconSize().width() == toolbars.ICON_PX == 24
assert tb.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly, "names under groups, not buttons"
assert tb._captions.isVisible()
assert "Reset selection" not in [a.text() for a in tb.actions()], "no Deselect button"
tips = {a.text(): a.toolTip() for a in tb.actions()}
assert tips["Filter"] == f"Filter ({shortcuts.native('filter')})", tips["Filter"]
assert tips["Show/hide panel"].startswith("Show/hide panel ("), tips

# Esc in the grid clears its selection (as a click on empty space does).
dt = w._data_tab
dt.table.selectColumn(1); app.processEvents()
assert dt.table.selectionModel().hasSelection()
dt.table.setFocus(); key(Qt.Key.Key_Escape, target=dt.table)
assert not dt.table.selectionModel().hasSelection(), "Esc deselects"

# Ctrl+B: the side panel, and its button follows.
panel_act = next(a for a in tb.actions() if a.text() == "Show/hide panel")
was = w.panel.isVisible()
key(Qt.Key.Key_B, C); assert w.panel.isVisible() != was and panel_act.isChecked() != was
key(Qt.Key.Key_B, C); assert w.panel.isVisible() == was

# Alt+Down / Alt+Up: the grid's layer.
layers = c.available_layers(); first = s.current_layer
key(Qt.Key.Key_Down, ALT); drain()
assert s.current_layer == layers[layers.index(first) + 1], (first, s.current_layer)
key(Qt.Key.Key_Up, ALT); drain(); assert s.current_layer == first

# The Data tab's buttons (the dialogs they open are stood in for).
hits = []
w._on_filter = lambda: hits.append("filter")
w._start_rename_column = lambda: hits.append("rename")
w._export_excel = lambda: hits.append("export")
QToolButton.showMenu = lambda self: hits.append(self.accessibleName())
w._sync_toolbar(w.tabbar.currentIndex()); app.processEvents()
for k, mods in ((Qt.Key.Key_F, C), (Qt.Key.Key_F2, Qt.KeyboardModifier.NoModifier),
                (Qt.Key.Key_E, C), (Qt.Key.Key_N, C)):
    key(k, mods)
assert hits == ["filter", "rename", "export", "New plot"], hits

# Settings and Close.
w._open_settings = lambda page=None: hits.append("settings")
closed = []
w._close_everything = lambda: closed.append(True)
key(Qt.Key.Key_Comma, C); key(Qt.Key.Key_W, C)
assert hits[-1] == "settings" and closed == [True], (hits, closed)

# A plot: Ctrl+0 and Ctrl+Shift+S press its buttons; tabs step with Ctrl+PgDown / Ctrl+Tab.
w._open_plot(PlotSpec(kind="2D Scatter", x="Demand X", y="Demand Y"), ("all", None, None)); drain()
plot_index = w.tabbar.currentIndex()
assert [n for n, _ in w.toolbar.group_rects()][:3] == ["View", "Show", "Save"], w.toolbar.group_rects()
pressed = []
w._plot_control = lambda tab, k, v=None: pressed.append(k)
key(Qt.Key.Key_0, C); key(Qt.Key.Key_S, C | SH)
assert pressed == ["reset_view", "screenshot"], pressed
key(Qt.Key.Key_PageDown, C); assert w.tabbar.currentIndex() == (plot_index + 1) % w.tabbar.count()
w.tabbar.setCurrentIndex(plot_index); app.processEvents()
key(Qt.Key.Key_Tab, C); assert w.tabbar.currentIndex() == (plot_index + 1) % w.tabbar.count(), "Ctrl+Tab"
key(Qt.Key.Key_Backtab, C | SH); assert w.tabbar.currentIndex() == plot_index, "Ctrl+Shift+Tab"
key(Qt.Key.Key_PageUp, C); assert w.tabbar.currentIndex() == plot_index - 1

# A pop-out plot window: a ribbon too, and Ctrl+B opens its panel.
w.tabbar.setCurrentIndex(plot_index); app.processEvents()
w._popout_plot(); app.processEvents(); win = w._detached[-1]
win.show(); win.activateWindow(); app.processEvents()
assert isinstance(win._toolbar, toolbars.Ribbon) and "Window" in [n for n, _ in win._toolbar.group_rects()]
assert win._panel.isHidden()
key(Qt.Key.Key_B, C, target=win); assert not win._panel.isHidden(), "Ctrl+B in a pop-out window"
# The help page lists every shortcut.
from pathlib import Path
page = (Path(shortcuts.__file__).parent / "assets/help/shortcuts.md").read_text(encoding="utf-8")
for name, (keys, _what) in shortcuts.SHORTCUTS.items():
    for k in keys:
        assert f"**{k}**" in page, f"{k} ({name}) is not in the Keyboard and mouse help page"
print("RIBBON AND SHORTCUT CHECKS PASS")
c.shutdown()
os._exit(0)
