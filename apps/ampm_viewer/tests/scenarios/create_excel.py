"""Create Excel from AMPM: full template (DHXML + parts CSV), reduced (CSV only), and a folder with neither.
After the build folder, a save dialog asks where the workbook goes (the build folder and its name to start
with; the dialog itself asks before replacing). Nothing is written without it."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import shutil, sys, tempfile, time
from pathlib import Path
from PyQt6.QtWidgets import QApplication, QFileDialog
app = QApplication([])
from openpyxl import load_workbook
from ampm_viewer.shell import controller as cmod
from ampm_viewer.shell.window import MainWindow
SRC = Path(sys.argv[1]); TMP = Path(tempfile.mkdtemp())
def light_copy(name, *, dhxml=True, csv=True, config=True):
    d = TMP / name; d.mkdir()
    for f in SRC.iterdir():
        if f.is_dir(): continue
        if f.suffix == ".dhxml" and not dhxml: continue
        if f.suffix == ".csv" and not csv: continue
        if f.name == "config.toml" and not config: continue
        if f.suffix == ".stl": continue
        shutil.copy(f, d / f.name)
    return d
w = MainWindow(); w.show(); c = w.controller
told, asked = [], []
cmod._tell = lambda parent, title, text, **k: told.append((title, text))
cmod._ask = lambda parent, title, text, **k: (asked.append(title), True)[1]
saves = []          # (suggested path, filter) of each save dialog
def run(d, save_as=None):
    """Pick build folder d; the save dialog returns save_as (None: accept its
    suggestion, "": cancel)."""
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: str(d))
    def save(parent, caption, suggested, filt, *a, **k):
        saves.append((suggested, filt))
        return (suggested if save_as is None else str(save_as), filt)
    QFileDialog.getSaveFileName = staticmethod(save)
    told.clear(); saves.clear(); w.backstage.act_new_excel.trigger()
    t0 = time.time()
    while c._side_thread is not None and time.time() - t0 < 120: app.processEvents(); time.sleep(0.01)
    for _ in range(20): app.processEvents()
    return told[-1] if told else (None, None)
def sheet(path):
    ws = load_workbook(path).active; rows = list(ws.iter_rows(values_only=True)); return rows

# 1. full build (dhxml + parts CSV), found via the folder: no config needed
d = light_copy("JR_full", config=False)
title, text = run(d); out = d / "JR_full.xlsx"
assert saves == [(str(out), "Excel workbook (*.xlsx)")], saves     # suggested: in the build, named after it
assert title == "Excel created" and out.is_file() and str(out) in text, (title, text)
assert not (d / "exports").exists(), "no exports folder any more"
rows = sheet(out); hdr = [str(h) for h in rows[0]]
print("full   :", len(rows) - 1, "rows; columns:", hdr[:12])
assert len(rows) - 1 >= 20 and not asked
assert list(d.iterdir()) and not (d / "config.toml").exists(), "must not create a DataStore/config"
# 2. somewhere else, and without the extension typed: saved there as .xlsx
other = TMP / "elsewhere"; other.mkdir()
title, text = run(d, other / "my template")
assert title == "Excel created" and (other / "my template.xlsx").is_file(), (title, text)
# 3. the save dialog cancelled: nothing written, nothing said
before = sorted(p.name for p in d.iterdir())
title, text = run(d, ""); assert (title, text) == (None, None) and sorted(p.name for p in d.iterdir()) == before
assert not asked, "replacing is the save dialog's question, not ours"
# 3. parts CSV only → reduced template, and the popup says so
d2 = light_copy("JR_csv_only", dhxml=False)
title, text = run(d2); out2 = d2 / "JR_csv_only.xlsx"
assert title == "Excel created" and out2.is_file() and "reduced" in text, (title, text)
print("reduced:", len(sheet(out2)) - 1, "rows")
# 4. dhxml only → still a (bounds-only) template
d3 = light_copy("JR_dhxml_only", csv=False)
title, text = run(d3); assert title == "Excel created" and (d3 / "JR_dhxml_only.xlsx").is_file(), text
# 5. nothing to build from → clear message straight away, no save dialog, no file
d4 = TMP / "empty"; d4.mkdir()
title, text = run(d4); assert title == "Couldn't create the Excel" and "nothing to build" in text, (title, text)
assert saves == [] and not any(d4.iterdir())
# 6. config.toml paths are honoured
d5 = light_copy("JR_cfg"); (d5 / "sub").mkdir(); shutil.move(str(next(d5.glob("*.csv"))), d5 / "sub" / "parts.csv")
(d5 / "config.toml").write_text("[paths]\nsource = 'x'\nparts_csv = 'sub/parts.csv'\n")
title, text = run(d5); r5 = sheet(d5 / "JR_cfg.xlsx")
assert title == "Excel created" and len(r5[0]) == len(rows[0]), (title, len(r5[0]), len(rows[0]))
print("CREATE-EXCEL CHECKS PASS"); c.shutdown()
