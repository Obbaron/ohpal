"""Frameless popups: all card dialogs draggable; LogWindow a frameless card;
no native QMessageBox left in the app's own popups."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import os, sys, tempfile
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication, QDialog, QWidget
app = QApplication([])
from ampm_analyzer.shell.card import DraggableCard
from ampm_analyzer.shell import (
    derive_dialog, excel_dialog, export_dialog, filter_dialog, import_parts_dialog,
    label_dialog, macro_dialog, message_dialog, part_calc_dialog, plot_dialog, logconsole,
)

# --- every styled popup is a DraggableCard ---------------------------------------
cards = {
    "DeriveColumnDialog": derive_dialog.DeriveColumnDialog,
    "ExcelImportDialog": excel_dialog.ExcelImportDialog,
    "ExcelExportDialog": export_dialog.ExcelExportDialog,
    "FilterConditionDialog": filter_dialog.FilterConditionDialog,
    "ImportPartsCSVDialog": import_parts_dialog.ImportPartsCSVDialog,
    "GroupLabelDialog": label_dialog.GroupLabelDialog,
    "_ListCard": macro_dialog._ListCard,
    "MacroPreviewDialog": macro_dialog.MacroPreviewDialog,
    "MacroIssuesDialog": macro_dialog.MacroIssuesDialog,
    "CardMessage": message_dialog.CardMessage,
    "PartCalcDialog": part_calc_dialog.PartCalcDialog,
    "NewPlotDialog": plot_dialog.NewPlotDialog,
    "LogWindow": logconsole.LogWindow,
}
for name, cls in cards.items():
    assert issubclass(cls, DraggableCard), name
    # DraggableCard must be first in the MRO so its mouse handlers win
    assert cls.__mro__.index(DraggableCard) < cls.__mro__.index(QWidget), name
    # none is a QMainWindow with native chrome any more
    from PyQt6.QtWidgets import QMainWindow
    assert not issubclass(cls, QMainWindow), name
print(f"{len(cards)} styled popups, all DraggableCard, none a native-frame window")

# --- the mixin actually moves a frameless window (fallback path) ------------------
cols = ["X", "Y", "Z"]
dlg = plot_dialog.NewPlotDialog("2D Scatter", cols, layers=[1,2,3])
dlg.show(); app.processEvents()
assert dlg.windowFlags() & Qt.WindowType.FramelessWindowHint
dlg._start_system_move = lambda: False   # force the manual-move fallback (headless)
start = dlg.pos()
def send(widget, kind, lp):
    gp = widget.mapToGlobal(lp)
    ev = QMouseEvent(kind, QPointF(lp), QPointF(gp), Qt.MouseButton.LeftButton,
                     Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, ev)
# press an inert spot on the card (top-left padding), then drag 40,25
send(dlg, QEvent.Type.MouseButtonPress, QPoint(6, 6))
assert dlg._drag_offset is not None, "press on an inert area starts a drag"
here = dlg.mapToGlobal(QPoint(6, 6))
ev = QMouseEvent(QEvent.Type.MouseMove, QPointF(46, 31), QPointF(here + QPoint(40, 25)),
                 Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
QApplication.sendEvent(dlg, ev)
moved = dlg.pos() - start
assert moved == QPoint(40, 25), moved
send(dlg, QEvent.Type.MouseButtonRelease, QPoint(46, 31))
assert dlg._drag_offset is None, "release ends the drag"
dlg.close()

# --- a press on a control does NOT drag ---------------------------------------------
dlg2 = plot_dialog.NewPlotDialog("2D Scatter", cols, layers=[1,2,3]); dlg2.show(); app.processEvents()
dlg2._start_system_move = lambda: False
btns = dlg2.findChildren(QWidget)
from PyQt6.QtWidgets import QComboBox, QPushButton
combo = next((w for w in btns if isinstance(w, (QComboBox, QPushButton))), None)
assert combo is not None
send(combo, QEvent.Type.MouseButtonPress, QPoint(5, 5))  # goes to the control, not the card
assert dlg2._drag_offset is None, "pressing a control must not begin a window drag"
dlg2.close()

# --- LogWindow is a frameless card, non-modal, with Close + a size grip ------------
from PyQt6.QtWidgets import QSizeGrip, QPushButton as PB
bus = logconsole.LogBus(); bus.write_text("hello log\n")
lw = logconsole.LogWindow(bus); lw.show(); app.processEvents()
assert lw.windowFlags() & Qt.WindowType.FramelessWindowHint and not lw.isModal()
assert "hello log" in lw.view.toPlainText()
assert lw.findChild(QSizeGrip) is not None, "a corner grip to resize"
labels = [b.text() for b in lw.findChildren(PB)]
assert "Close" in labels and "Export log" in labels and "Clear" in labels, labels
lw.close()
print("drag moves on inert areas, not on controls; LogWindow is a frameless card")

# --- the app's own popups no longer call the native QMessageBox ---------------------
import ampm_analyzer.shell.window as wmod, ampm_analyzer.shell.plot_window as pwmod, ampm_analyzer.shell.logconsole as lcmod, inspect
for mod in (wmod, pwmod, lcmod):
    src = inspect.getsource(mod)
    assert "QMessageBox" not in src, f"{mod.__name__} still references QMessageBox"
print("no native QMessageBox left in window / plot_window / logconsole")
print("ALL CARD CHECKS PASS")
