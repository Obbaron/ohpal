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
assert tb.iconSize().width() == toolbars.ICON_PX == 24
assert tb.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly, "names under groups, not buttons"

def check_aligned(tb, where):
    """Each group is one widget, buttons over name: the names sit on one
    line, centred under their buttons, inside their group; the separators
    fall between groups and run their full height."""
    from PyQt6.QtCore import QPoint
    from PyQt6.QtWidgets import QToolButton as TB
    shown = [g for g in tb._groups if g.isVisible()]
    assert shown, where
    for g in shown:
        cap, row = g.caption, g.row
        assert cap.isVisible() and cap.text() == g.name, (where, g.name)
        assert cap.width() >= cap.sizeHint().width() - 1, (where, g.name, "name cut")
        assert cap.geometry().left() >= 0 and cap.geometry().right() <= g.width(), (where, g.name)
        cc = cap.mapTo(tb, cap.rect().center()).x()
        rc = row.mapTo(tb, row.rect().center()).x()
        assert abs(cc - rc) <= 1, (where, g.name, cc, rc, "name centred under its buttons")
        assert row.height() == shown[0].row.height(), (where, g.name, "one row height")
        for btn in row.findChildren(TB):
            if btn.isVisible():  # every button above its group's name
                assert btn.mapTo(tb, QPoint(0, btn.height())).y() <= cap.mapTo(tb, QPoint(0, 0)).y() + 1
    tops = {g.caption.mapTo(tb, QPoint(0, 0)).y() for g in shown}
    assert len(tops) == 1, (where, "names on one line", tops)
    heights = {g.height() for g in shown}
    assert len(heights) == 1, (where, heights)
    seps = [tb.widgetForAction(a) for a in super(toolbars.Ribbon, tb).actions() if a.isSeparator()]
    seps = [s for s in seps if s is not None and s.isVisible()]
    assert len(seps) >= len(shown) - 1, (where, len(seps), len(shown))
    for left, right in zip(shown, shown[1:]):
        between = [s for s in seps if left.geometry().right() < s.geometry().center().x() < right.geometry().left()]
        assert between, (where, "a separator between", left.name, right.name)
        s = between[0].geometry()
        assert s.top() <= left.geometry().top() + 4 and s.bottom() >= left.geometry().bottom() - 4, (
            where, "separator runs the group's height", s, left.geometry())
    return shown

check_aligned(tb, "data ribbon")
# A menu button is found as before: its action stands for it.
menu_btns = [tb.widgetForAction(a) for a in tb.actions()
             if getattr(tb.widgetForAction(a), "menu", lambda: None)() is not None]
assert {b.accessibleName() for b in menu_btns} >= {"Show/hide columns", "Add column", "New plot"}
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
check_aligned(w.toolbar, "plot ribbon")
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
check_aligned(win._toolbar, "pop-out ribbon")
assert win._panel.isHidden()
key(Qt.Key.Key_B, C, target=win); assert not win._panel.isHidden(), "Ctrl+B in a pop-out window"
# A narrow pop-out window: whole groups go into the » menu; the rest still
# line up. Wide again: all back.
from PyQt6.QtWidgets import QToolButton as _TB
win.resize(win.minimumSizeHint().width(), 500)
for _ in range(20): app.processEvents()
shown = check_aligned(win._toolbar, "narrow pop-out")
assert len(shown) < len(win._toolbar._groups), "some groups overflow"
ext = [b for b in win._toolbar.findChildren(_TB) if b.objectName() == "qt_toolbar_ext_button"]
assert ext and ext[0].isVisible(), "the » button"
assert not ext[0].icon().isNull() and ext[0].toolTip() == "More"
# The » drops a menu of the hidden groups: each name, then its buttons.
from PyQt6.QtWidgets import QMenu as _M
hidden = [g.name for g in win._toolbar._groups if not g.isVisible()]
dropped = []
_exec = _M.exec
_M.exec = lambda self, *a: dropped.append([(x.text(), x.isSeparator()) for x in self.actions()])
QTest.mouseClick(ext[0], Qt.MouseButton.LeftButton); app.processEvents()
for _ in range(5): app.processEvents()
_M.exec = _exec
assert dropped, "the » opened a menu"
assert not ext[0].isChecked(), "and didn't toggle Qt's own expansion"
texts = [x for x, _sep in dropped[0]]
for name in hidden:
    assert name in texts, (name, texts)
assert "Screenshot" in texts or "Pop out" in texts or "Dock in" in texts, texts

win.resize(1300, 700)
for _ in range(20): app.processEvents()
assert len(check_aligned(win._toolbar, "pop-out wide again")) == len(win._toolbar._groups)
win.close(); app.processEvents()
# The main window at its narrowest still has room for every Data group.
w.tabbar.setCurrentIndex(w.stack.indexOf(w._data_tab)); app.processEvents()
w.resize(w.minimumSizeHint().width(), 600)
for _ in range(20): app.processEvents()
assert len(check_aligned(w.toolbar, "narrowest main")) == len(w.toolbar._groups), w.width()
w.resize(1400, 800)
for _ in range(10): app.processEvents()
# Rebuilt (recording swaps Record for Stop): still one set of groups, lined up.
n_groups = len(w.toolbar._groups)
w.recorder.start(); app.processEvents(); w._sync_toolbar(w.tabbar.currentIndex()); app.processEvents()
assert len(w.toolbar._groups) == n_groups and "Stop recording and save the macro" in [a.text() for a in w.toolbar.actions()]
check_aligned(w.toolbar, "recording")
w.recorder.cancel(); w._sync_toolbar(w.tabbar.currentIndex()); app.processEvents()
# Hiding an action hides its button (the group closes up).
act = next(a for a in w.toolbar.actions() if a.text() == "Filter")
act.setVisible(False); app.processEvents()
assert not w.toolbar.widgetForAction(act).isVisible()
act.setVisible(True); app.processEvents()
assert w.toolbar.widgetForAction(act).isVisible()
# Clicking a group's bare background still deselects.
dt = w._data_tab
dt.table.selectColumn(1); app.processEvents()
g = w.toolbar._groups[0]
QTest.mouseClick(g.caption, Qt.MouseButton.LeftButton); app.processEvents()
assert not dt.table.selectionModel().hasSelection(), "a click on a group's name deselects"
# The help page lists every shortcut.
from pathlib import Path
page = (Path(shortcuts.__file__).parent / "assets/help/shortcuts.md").read_text(encoding="utf-8")
for name, (keys, _what) in shortcuts.SHORTCUTS.items():
    for k in keys:
        assert f"**{k}**" in page, f"{k} ({name}) is not in the Keyboard and mouse help page"
print("RIBBON AND SHORTCUT CHECKS PASS")
c.shutdown()
os._exit(0)
