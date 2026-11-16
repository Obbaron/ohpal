"""Unexpected errors: report + dialog, the app keeps running; version single-sourced;
the 1.x GUI is gone."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import importlib.util, os, sys, tempfile, threading, time
from pathlib import Path
from PyQt6.QtCore import QTimer, QEventLoop
from PyQt6.QtWidgets import QApplication

import ampm_analyzer
assert ampm_analyzer.__version__ == "2.0.0" and callable(ampm_analyzer.main)
for gone in ("ampm_analyzer.main", "ampm_analyzer.views"):
    assert importlib.util.find_spec(gone) is None, gone
assert "ampm_analyzer.shell" not in sys.modules, "importing the package stays light"
print("version 2.0.0 from __init__; legacy main.py and views/ gone")

app = QApplication([]); app.setOrganizationName("AMPM"); app.setApplicationName("AMPM Analyzer")
from ampm_analyzer.shell import crash
from ampm_analyzer.shell.logconsole import LogBus, StreamTee
bus = LogBus(); bus.log_line("opened build JR299"); sys.stderr = StreamTee(bus, sys.stderr)  # as app.main does
crash.install(bus)
folder = crash.report_dir()
assert folder.parts[-3:] == ("AMPM", "AMPM Analyzer", "crash-reports"), folder
fatal = (folder / "fatal.log").read_text(); assert "AMPM Analyzer 2.0.0 started" in fatal

def run_until(cond, limit=10):
    t0 = time.time()
    while not cond() and time.time() - t0 < limit:
        app.processEvents(); time.sleep(0.01)
    return cond()

seen = {}
def on_dialog():          # while the first dialog is open: another error, then keep working
    d = crash._state["dialog"]
    seen["text"] = [w.text() for w in d.findChildren(__import__("PyQt6.QtWidgets", fromlist=["QLabel"]).QLabel)]
    QTimer.singleShot(0, lambda: (_ for _ in ()).throw(KeyError("second")))
    def later():
        seen["more"] = d.more_label.text()
        d.toggle.click(); seen["details"] = d.details.toPlainText()
        next(b for b in d.findChildren(__import__("PyQt6.QtWidgets", fromlist=["QPushButton"]).QPushButton)
             if b.text() == "Keep working").click()
    QTimer.singleShot(150, later)
def boom():
    QTimer.singleShot(50, on_dialog)
    raise ValueError("bad value in a slot " + "x" * 400)
alive = []
QTimer.singleShot(0, boom)
QTimer.singleShot(600, lambda: alive.append(1))      # the event loop carries on
assert run_until(lambda: alive and "details" in seen), seen.keys()
assert crash._state["dialog"] is None
body = " ".join(seen["text"])
assert "ValueError: bad value in a slot" in body and body.count("x") < 400, "summary is shortened"
assert str(folder) in body and "Something went wrong" in body
assert seen["more"].startswith("1 more error since this one"), seen["more"]
assert "Traceback" in seen["details"] and "boom" in seen["details"]
reports = sorted(folder.glob("crash-*.log")); assert len(reports) == 2, reports
r = reports[0].read_text()
assert "AMPM Analyzer 2.0.0" in r and "ValueError" in r and "opened build JR299" in r and "Qt 6" in r
assert "KeyError: 'second'" in reports[1].read_text()
assert "ValueError" in bus.history(), "the traceback also reaches the in-app log"
print("slot error: report written, dialog shown, a second error counted on it, app kept running")

# a worker thread: reported, dialog opens on the main thread
where = {}
def check_thread_dialog():
    d = crash._state["dialog"]
    if d is None: QTimer.singleShot(20, check_thread_dialog); return
    where["main"] = threading.current_thread() is threading.main_thread()
    d.accept()
QTimer.singleShot(20, check_thread_dialog)
t = threading.Thread(target=lambda: 1 / 0, name="Worker-7"); t.start(); t.join()
assert run_until(lambda: "main" in where) and where["main"]
last = sorted(folder.glob("crash-*.log"))[-1].read_text()
assert "(in Worker-7)" in last and "ZeroDivisionError" in last
print("thread error: reported with the thread's name; dialog on the main thread")

# Quit ends the event loop
loop = QEventLoop(); quit_seen = []
app.aboutToQuit.connect(lambda: quit_seen.append(1))
def press_quit():
    d = crash._state["dialog"]
    if d is None: QTimer.singleShot(20, press_quit); return
    next(b for b in d.findChildren(__import__("PyQt6.QtWidgets", fromlist=["QPushButton"]).QPushButton) if b.text() == "Quit").click()
QTimer.singleShot(0, lambda: (_ for _ in ()).throw(RuntimeError("quit me")))
QTimer.singleShot(20, press_quit)
QTimer.singleShot(5000, loop.quit)
app.aboutToQuit.connect(loop.quit)
code = app.exec()
assert quit_seen, "Quit closes the app"
print("Quit closes the app")

# old reports are pruned to the newest 30
for i in range(40):
    (folder / f"crash-20200101-0000{i:02d}-000000.log").write_text("old")
crash.write_report(OSError, OSError("x"), None)
assert len(list(folder.glob("crash-*.log"))) == 30
# a report must never raise, even when the folder cannot be written
real = crash.report_dir; crash.report_dir = lambda: (_ for _ in ()).throw(PermissionError("ro"))
assert crash.write_report(OSError, OSError("x"), None) is None; crash.report_dir = real
print("reports pruned to 30; an unwritable folder never raises")

# startup failure: report + a Close-only dialog, then exit 1
from ampm_analyzer.shell import app as appmod, window as winmod
shown = {}
def fake_exec(self):
    shown["buttons"] = [b.text() for b in self.findChildren(__import__("PyQt6.QtWidgets", fromlist=["QPushButton"]).QPushButton) if not b.isHidden()]
    shown["body"] = " ".join(l.text() for l in self.findChildren(__import__("PyQt6.QtWidgets", fromlist=["QLabel"]).QLabel))
    return 0
crash.CrashDialog.exec = fake_exec
class Broken:
    def __init__(self, **k): raise RuntimeError("window failed")
winmod.MainWindow = Broken
appmod.QApplication = lambda argv: app
try:
    appmod.main(); raise SystemExit("should have exited")
except SystemExit as e:
    assert e.code == 1, e.code
assert "could not start" in shown["body"] and "RuntimeError: window failed" in shown["body"]
assert "Keep working" not in shown["buttons"] and "Close" in shown["buttons"], shown["buttons"]
assert "(starting up)" in sorted(folder.glob("crash-*.log"))[-1].read_text()
print("CRASH CHECKS PASS")
