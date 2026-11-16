"""The macro folder: default in Documents, configurable in Settings, used by Save and
Browse, listed on the Run menu; an unreachable folder falls back to the default."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import os, sys, tempfile, time
BUILD = sys.argv[1]
from pathlib import Path
from PyQt6.QtCore import QEventLoop, QTimer, QStandardPaths
from PyQt6.QtWidgets import QApplication, QFileDialog, QToolButton
app = QApplication([]); app.setOrganizationName("AMPM"); app.setApplicationName("AMPM Analyzer")
from ampm_analyzer.shell import controller as cmod, macros, window as wmod
from ampm_analyzer.shell.window import MainWindow

docs = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation))
assert macros.default_folder() == docs / "AMPM Analyzer" / "Macros"
assert macros.folder() == macros.default_folder() and macros.is_default_folder()
assert not macros.default_folder().exists() and macros.ensure_folder().is_dir()
print("default:", macros.default_folder())

cmod._tell = lambda *a, **k: None
w = MainWindow(); w.resize(1200, 760); w.show(); c, s = w.controller, w.session
loop = QEventLoop(); s.queryReady.connect(lambda *_: loop.quit()); QTimer.singleShot(240000, loop.quit)
c.open_recent(BUILD); loop.exec()
for _ in range(50): app.processEvents(); time.sleep(0.01)

asked = {}
def fake_save(parent, title, start, filt):
    asked["save"] = start
    return str(Path(start).parent / "cov by part.macro.json"), filt
def fake_open(parent, title, start, filt):
    asked["open"] = start
    return "", filt
QFileDialog.getSaveFileName = staticmethod(fake_save); QFileDialog.getOpenFileName = staticmethod(fake_open)
step = {"op": "filter_add", "params": {"condition": "[layer] > 0"}}
from ampm_analyzer.shell import macro_dialog
from PyQt6.QtWidgets import QDialog
macro_dialog.MacroSaveDialog.exec = lambda self: QDialog.DialogCode.Accepted  # Stop: nothing asked when run
w._save_recording([step])
assert Path(asked["save"]).parent == macros.default_folder(), asked
saved = macros.default_folder() / "cov by part.macro.json"; assert saved.is_file()
(macros.default_folder() / "another.macro.json").write_text(saved.read_text())
(macros.default_folder() / "notes.txt").write_text("not a macro")
w._run_macro(); assert Path(asked["open"]) == macros.default_folder()
print("Save and Browse start in the macro folder")

def run_menu():
    w.tabbar.setCurrentIndex(w.stack.indexOf(w._data_tab)); w._sync_toolbar(w.tabbar.currentIndex()); app.processEvents()
    btn = next(b for b in w.toolbar.findChildren(QToolButton) if b.toolTip() == "Run a macro")
    return [(a.text(), a.isSeparator()) for a in btn.menu().actions()]
items = run_menu(); texts = [t for t, sep in items if t]
print("Run menu:", texts)
assert texts[:2] == ["Recent", "cov by part"] and texts[2:4] == ["Macro folder", "another"], texts
assert "notes" not in " ".join(texts) and texts[-2:] == ["Browse…", "Open macro folder"]

# Settings: shows the folder; change it; the menu and dialogs follow
m = w._settings_menu(); labels = [a.text() for a in m.actions() if a.text()]
print("Settings:", labels)
assert "Macros" in labels and any(l.startswith("Folder: ") for l in labels)
assert "Change macro folder…" in labels and "Open macro folder" in labels and "Use the default folder" not in labels
shared = Path(tempfile.mkdtemp()) / "team-macros"; shared.mkdir()
(shared / "team step.macro.json").write_text(saved.read_text())
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: str(shared))
w._choose_macro_folder()
assert macros.folder() == shared and not macros.is_default_folder()
texts = [t for t, _ in run_menu() if t]
assert "team step" in texts and "another" not in texts and "cov by part" in texts, texts   # recent stays
m = w._settings_menu(); labels = [a.text() for a in m.actions() if a.text()]
assert "Use the default folder" in labels
w._run_macro(); assert Path(asked["open"]) == shared
print("custom folder: listed, used by Browse; recent macros stay on the menu")

# an unreachable folder: dialogs fall back to the default, with a note
blocker = Path(tempfile.mkdtemp()) / "a-file"; blocker.write_text("x")
macros.set_folder(blocker / "macros")          # can't be created: like an offline share
notes = []; real_status = w.set_status; w.set_status = lambda t, *a, **k: (notes.append(t), real_status(t, *a, **k))
assert macros.ensure_folder() is None and macros.in_folder() == []
w._run_macro(); assert Path(asked["open"]) == macros.default_folder()
assert any("isn't available" in n for n in notes), notes
w._reset_macro_folder(); assert macros.is_default_folder() and macros.folder() == macros.default_folder()
macros.set_folder(macros.default_folder()); assert macros.is_default_folder(), "choosing the default = default"
print("offline folder falls back to the default; reset works")
c.shutdown()
print("MACRO FOLDER CHECKS PASS")
