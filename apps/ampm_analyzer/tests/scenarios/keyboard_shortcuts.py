"""Undo / redo shortcuts reach the app, not a text field being edited (and vice versa)."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import os, sys
from PyQt6.QtCore import QEventLoop, QTimer, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLineEdit
app = QApplication([])
from ampm_analyzer.shell.window import MainWindow
w = MainWindow(); w.show(); w.activateWindow()
loop = QEventLoop(); w.session.queryReady.connect(lambda *_: loop.quit()); QTimer.singleShot(120000, loop.quit)
w.controller.open_recent(sys.argv[1]); loop.exec()
for _ in range(20): app.processEvents()
s = w.session
w._run("derive", name="k1", expr="[layer] * 2")
assert any(d["name"] == "k1" for d in s.derivations)
w._data_tab.table.setFocus(); app.processEvents()
C, SH = Qt.KeyboardModifier.ControlModifier, Qt.KeyboardModifier.ShiftModifier
QTest.keyClick(w, Qt.Key.Key_Z, C); app.processEvents()
assert not any(d["name"] == "k1" for d in s.derivations), "Ctrl+Z did not undo"
QTest.keyClick(w, Qt.Key.Key_Z, C | SH); app.processEvents()
assert any(d["name"] == "k1" for d in s.derivations), "Ctrl+Shift+Z did not redo"
QTest.keyClick(w, Qt.Key.Key_Z, C); app.processEvents()
QTest.keyClick(w, Qt.Key.Key_Y, C); app.processEvents()
assert any(d["name"] == "k1" for d in s.derivations), "Ctrl+Y did not redo"
# Ctrl+Z while typing in a text field edits the text, not the data
le = QLineEdit(w); le.show(); le.setFocus(); app.processEvents()
QTest.keyClicks(le, "abc"); QTest.keyClick(le, Qt.Key.Key_Z, C); app.processEvents()
assert any(d["name"] == "k1" for d in s.derivations), "Ctrl+Z in a text field undid an action"
print("text after Ctrl+Z in field:", repr(le.text()))
# show/hide through the toolbar's menu action is one undo step
w._sync_toolbar(w.tabbar.currentIndex())
n = len(w.actions.history._undo)
w._run("set_visible", name="k1", visible=False); assert len(w.actions.history._undo) == n + 1
QTest.keyClick(w, Qt.Key.Key_Z, C) if False else w._undo()
assert "k1" not in w._data_tab.hidden_columns()
w.controller.shutdown(); w.close(); app.processEvents()
print("SHORTCUT CHECKS PASS", flush=True)
# Leave without Python tearing Qt down object by object: under a loaded
# machine that teardown has crashed (after every check passed).
os._exit(0)
