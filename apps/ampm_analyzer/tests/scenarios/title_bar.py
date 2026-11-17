"""Frameless main window: the tab row as title bar, window buttons, resize grips."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QIcon, QMouseEvent, QPixmap, QColor
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from ampm_analyzer.shell import titlebar
from ampm_analyzer.shell.app import _app_icon
from ampm_analyzer.shell.window import MainWindow

w = MainWindow(); w.resize(1100, 640)
print("app icon loads here:", not _app_icon().isNull())
pm = QPixmap(32, 32); pm.fill(QColor("#3366cc")); w.setWindowIcon(QIcon(pm))
w.show(); app.processEvents()

# --- frameless, with the hints the taskbar / system menu rely on ------------------
f = w.windowFlags()
assert f & Qt.WindowType.FramelessWindowHint and f & Qt.WindowType.WindowMinimizeButtonHint
assert f & Qt.WindowType.WindowMaximizeButtonHint and f & Qt.WindowType.WindowSystemMenuHint
assert w.windowTitle() == "AMPM Analyzer", "the taskbar still shows the name"

# --- the tab row is the title bar ---------------------------------------------------
bar = w._title_bar
assert isinstance(bar, titlebar.TitleBar) and bar.height() >= titlebar.BAR_HEIGHT
assert w.tabbar.parent() is bar and w._win_btns.parent() is bar
for key in ("undo", "redo", "help", "settings"): assert w._global_btns[key].parent() is bar
order = sorted([w._title_icon, w.tabbar, w._global_btns["undo"], w._global_btns["settings"], w._win_btns], key=lambda x: x.x())
assert order == [w._title_icon, w.tabbar, w._global_btns["undo"], w._global_btns["settings"], w._win_btns]
assert w._title_icon.pixmap() is not None and not w._title_icon.pixmap().isNull(), "the window icon shows on the bar"
wb = w._win_btns
assert wb.mapTo(w, QPoint(wb.width(), 0)).x() >= w.width() - 2 and wb.mapTo(w, QPoint(0, 0)).y() <= 2, "window buttons sit in the top-right corner"
assert [b.toolTip() for b in (wb.min_btn, wb.max_btn, wb.close_btn)] == ["Minimise", "Maximise", "Close"]
assert all(not b.icon().isNull() for b in (wb.min_btn, wb.max_btn, wb.close_btn))
print("frameless; bar holds icon, tabs, undo/redo/help/settings, then minimise / maximise / close")

# --- drag the empty stretch to move; buttons keep their clicks -------------------------
moves = []
bar._start_move = lambda: moves.append(1) or True
def press(widget, pos, kind=QEvent.Type.MouseButtonPress):
    ev = QMouseEvent(kind, QPointF(pos), QPointF(widget.mapToGlobal(pos)), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, ev)
gap = QPoint((w.tabbar.geometry().right() + w._global_btns["undo"].x()) // 2, bar.height() // 2)
assert bar.childAt(gap) is None
press(bar, gap); assert moves == [1], "dragging the empty stretch moves the window"
press(w._title_icon, QPoint(5, 5)); assert moves == [1, 1], "so does dragging the icon"
opened = []
w._open_help = lambda: opened.append(1)
w._global_btns["undo"].setEnabled(True)
from PyQt6.QtTest import QTest
QTest.mouseClick(w._global_btns["settings"], Qt.MouseButton.LeftButton) if False else None
press(w._global_btns["undo"], QPoint(5, 5)); assert moves == [1, 1], "a button press never starts a move"
press(w.tabbar, QPoint(10, 10)); assert moves == [1, 1], "nor does a click on a tab"

# --- maximise / restore: double-click and the button ---------------------------------------
grips = w._grips.grips()
assert len(grips) == 8 and all(g.isVisible() for g in grips.values())
assert w.contentsMargins().left() == 1
normal = w.size()
press(bar, gap, QEvent.Type.MouseButtonDblClick); app.processEvents()
assert w.isMaximized() and wb.max_btn.toolTip() == "Restore"
assert not any(g.isVisible() for g in grips.values()) and w.contentsMargins().left() == 0, "maximised: no grips, no border"
wb.max_btn.click(); app.processEvents()
assert not w.isMaximized() and wb.max_btn.toolTip() == "Maximise" and all(g.isVisible() for g in grips.values()) and w.contentsMargins().left() == 1
wb.max_btn.click(); app.processEvents(); assert w.isMaximized()
wb.max_btn.click(); app.processEvents(); assert not w.isMaximized()
print("double-click and the button maximise / restore; grips and border follow the state")

# --- resize grips hug the edges and stay on top -----------------------------------------------
w.resize(1000, 600); app.processEvents()
g = grips
assert g["right"].geometry().right() == w.width() - 1 and g["bottom"].geometry().bottom() == w.height() - 1
assert g["top_left"].geometry().topLeft() == QPoint(0, 0) and g["bottom_right"].geometry().bottomRight() == QPoint(w.width() - 1, w.height() - 1)
assert g["left"].cursor().shape() == Qt.CursorShape.SizeHorCursor and g["top"].cursor().shape() == Qt.CursorShape.SizeVerCursor
assert g["top_left"].cursor().shape() == Qt.CursorShape.SizeFDiagCursor and g["top_right"].cursor().shape() == Qt.CursorShape.SizeBDiagCursor
assert w.childAt(QPoint(1, 300)) is g["left"] and w.childAt(QPoint(w.width() - 2, 300)) is g["right"] and w.childAt(QPoint(500, w.height() - 2)) is g["bottom"]
edges = {n: gr._edges for n, gr in g.items()}
assert edges["bottom_right"] == (Qt.Edge.BottomEdge | Qt.Edge.RightEdge) and edges["left"] == Qt.Edge.LeftEdge
# the close button stays clickable below the thin top strip
inner = wb.close_btn.mapTo(w, QPoint(20, 16)); hit = w.childAt(inner)
assert hit is wb.close_btn, hit

# --- theme switch retints the window buttons; minimise; close ------------------------------------
before = wb.min_btn.icon().cacheKey(); w._win_btns.retint("#ff0000"); assert wb.min_btn.icon().cacheKey() != before
wb.min_btn.click(); app.processEvents(); assert w.isMinimized()
w.showNormal(); app.processEvents()
closed = []
orig = w.closeEvent
w.closeEvent = lambda e: (closed.append(1), orig(e))[1]
wb.close_btn.click(); app.processEvents()
assert closed == [1] and not w.isVisible()
print("grips on every edge and corner; close button still clickable; minimise and close work")
print("ALL TITLE BAR CHECKS PASS")
