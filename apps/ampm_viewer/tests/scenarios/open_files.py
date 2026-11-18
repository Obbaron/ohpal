"""Opening a .ampmplot from outside the app (the installers make it the app's
file type). Windows / Linux: a second start with the file hands it to the
running app over a local socket and quits, and the plot opens there (a plain
start still opens a new window). macOS: a FileOpen event, kept until the
window is up. Anything not a .ampmplot is ignored."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import os, subprocess, sys, time
from dataclasses import asdict
import polars as pl
from PyQt6.QtCore import QEvent
from ampm_viewer.shell.app import _App
app = _App([])
from ampm_viewer.shell import controller as cmod, plot_library, single_instance
from ampm_viewer.shell.plotspec import PlotSpec
from ampm_viewer.shell.window import MainWindow

told = []
cmod._tell = lambda *a, **k: told.append(a[1:])
def pump(n=20):
    for _ in range(n): app.processEvents(); time.sleep(0.005)

# A plot-library file, as the plot toolbar's "Save to plot library" writes.
def plot_file(name, title):
    df = pl.DataFrame({"X": [0.0, 1.0, 2.0, 3.0], "Y": [0.0, 1.0, 0.5, 2.0],
                       "v": [1.0, 2.0, 3.0, 4.0], "layer": [1, 1, 2, 2]})
    info = {"format": plot_library.FORMAT, "version": plot_library.VERSION,
            "app_version": "test", "spec": asdict(PlotSpec(kind="2D Scatter", x="X", y="Y", color="v")),
            "span": ["all", None, None], "title": title, "row_filter": [], "appearance": {},
            "build": "JR000", "saved": "2026-11-18T03:00:00", "renames": {},
            "layer_column": "layer", "layers": [1, 2], "rows": df.height}
    path = _harness.ROOT / name
    plot_library.save_frozen(path, info, df)
    return str(path)
first, second, third = (plot_file(f"p{i}.ampmplot", f"Shared plot {i}") for i in (1, 2, 3))

assert single_instance.openable(["a.AMPMPLOT", "b.txt", "--x", first]) == ["a.AMPMPLOT", first]
assert single_instance.forward([first]) is False, "nothing running yet: open it yourself"

w = MainWindow(); w.show(); pump()
titles = lambda: [t.context["frozen"]["title"] for t in w._plot_tabs]
class FileOpen:  # what macOS sends (PyQt can't make a QFileOpenEvent)
    def __init__(self, path): self.path = path
    def type(self): return QEvent.Type.FileOpen
    def file(self): return self.path

# macOS: a FileOpen event before the window is ready waits, then opens.
assert app.event(FileOpen(first)); pump()
assert app.pending == [first] and titles() == []
app.open_files = w.open_files
w.open_files(app.pending); app.pending.clear(); pump()
assert titles() == ["Shared plot 1"] and w.tabbar.currentIndex() == w.tabbar.count() - 1
assert app.event(FileOpen(second)); pump()
assert titles() == ["Shared plot 1", "Shared plot 2"]
print("macOS FileOpen: kept until the window is up, then opened as plot tabs")

# Windows / Linux: a second start with the file hands it over and ends.
listener = single_instance.Listener(w.open_files, app)
assert listener.listening
env = dict(os.environ, PYTHONUTF8="1")
proc = subprocess.Popen([sys.executable, "-m", "ampm_viewer", third, "not-a-plot.txt"],
                        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
t0 = time.time()
while proc.poll() is None and time.time() - t0 < 60:
    pump(2)
if proc.poll() is None:
    proc.kill()
    raise AssertionError("the second start kept running instead of handing the file over")
took = time.time() - t0
out = proc.stdout.read().decode(errors="replace")
assert proc.returncode == 0, out
t0 = time.time()
while "Shared plot 3" not in titles() and time.time() - t0 < 10:
    pump(2)
assert titles() == ["Shared plot 1", "Shared plot 2", "Shared plot 3"], titles()
print(f"second start handed the file over and quit ({took:.1f} s); opened here")

# A file that isn't a plot, or is gone: a notice, no tab, the app carries on.
from ampm_viewer.shell import message_dialog
notices = []
message_dialog.tell = lambda _p, title, text, **k: notices.append(text)
w.open_files([str(_harness.ROOT / "gone.ampmplot")]); pump()
assert len(titles()) == 3 and notices and "can't be opened" in notices[0]
print("a missing file: a notice, nothing opened")

# A second listener (another copy of the app) doesn't take the name over.
other = single_instance.Listener(lambda p: None, app)
assert not other.listening and listener.listening
assert not told, told
listener.close(); other.close()
print("ALL OK")
w.controller.shutdown()
