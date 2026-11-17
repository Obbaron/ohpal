"""Create Excel from AMPM: full template (DHXML + parts CSV), reduced (CSV only), and a folder with neither."""
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
def run(d):
    QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: str(d))
    told.clear(); w.backstage.act_new_excel.trigger()
    t0 = time.time()
    while c._side_thread is not None and time.time() - t0 < 120: app.processEvents(); time.sleep(0.01)
    for _ in range(20): app.processEvents()
    return told[-1]
def sheet(path):
    ws = load_workbook(path).active; rows = list(ws.iter_rows(values_only=True)); return rows

# 1. full build (dhxml + parts CSV), found via the folder: no config needed
d = light_copy("JR_full", config=False)
title, text = run(d); out = d / "exports" / "JR_full.xlsx"
assert title == "Excel created" and out.is_file(), (title, text)
rows = sheet(out); hdr = [str(h) for h in rows[0]]
print("full   :", len(rows) - 1, "rows; columns:", hdr[:12])
assert len(rows) - 1 >= 20 and not asked
assert list(d.iterdir()) and not (d / "config.toml").exists(), "must not create a DataStore/config"
# 2. again → asks before replacing
run(d); assert asked == ["Replace the existing Excel?"], asked
# 3. parts CSV only → reduced template, and the popup says so
d2 = light_copy("JR_csv_only", dhxml=False)
title, text = run(d2); out2 = d2 / "exports" / "JR_csv_only.xlsx"
assert title == "Excel created" and out2.is_file() and "reduced" in text, (title, text)
print("reduced:", len(sheet(out2)) - 1, "rows")
# 4. dhxml only → still a (bounds-only) template
d3 = light_copy("JR_dhxml_only", csv=False)
title, text = run(d3); assert title == "Excel created" and (d3 / "exports" / "JR_dhxml_only.xlsx").is_file(), text
# 5. nothing to build from → clear message, no exports folder left with a file
d4 = TMP / "empty"; d4.mkdir()
title, text = run(d4); assert title == "Couldn't create the Excel" and "nothing to build" in text, (title, text)
assert not any((d4 / "exports").glob("*")) if (d4 / "exports").exists() else True
# 6. config.toml paths are honoured
d5 = light_copy("JR_cfg"); (d5 / "sub").mkdir(); shutil.move(str(next(d5.glob("*.csv"))), d5 / "sub" / "parts.csv")
(d5 / "config.toml").write_text("[paths]\nsource = 'x'\nparts_csv = 'sub/parts.csv'\n")
title, text = run(d5); r5 = sheet(d5 / "exports" / "JR_cfg.xlsx")
assert title == "Excel created" and len(r5[0]) == len(rows[0]), (title, len(r5[0]), len(rows[0]))
print("CREATE-EXCEL CHECKS PASS"); c.shutdown()
