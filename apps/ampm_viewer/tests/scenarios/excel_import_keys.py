"""Add from Excel on the samples template: its part_id is "12" where the grid's
is "Part(12)", and both are matched. The dialog counts how many keys each grid
column holds on the layer shown, starts on the best one (part_id), and asks
before adding a column nothing matches (the empty column a wrong "Match on
grid column", such as Start time, used to give without a word). The status
says how many rows got a value.

It opens on the right choices for a filled-in template, with nothing to change:
key part_id, value the first measurement someone added (then the next one, once
that's imported), match on part_id. A plain workbook, without the template's
shading, gets the same."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import sys, time
from pathlib import Path
BUILD = sys.argv[1]
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog
app = QApplication([])
from openpyxl import load_workbook
from ohpal.ampm.template import make_template
from ampm_viewer.shell import controller as cmod, derive, excel_dialog, message_dialog
from ampm_viewer.shell.window import MainWindow

cmod._tell = lambda *a, **k: None
asked = []
answer = [False]
def fake_ask(parent, title, text, **k):
    asked.append((title, text)); return answer[0]
excel_dialog.ask = fake_ask
message_dialog.ask = fake_ask

w = MainWindow(); w.resize(1200, 760); w.show(); c, s = w.controller, w.session
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
pid = c.part_id_display()
assert pid in s.result.df.columns, "this build opens with parts assigned"

# The samples template for this build, with a density per part.
root = Path(BUILD)
xlsx = make_template(next(root.glob("*.dhxml")), _harness.ROOT / "samples.xlsx",
                     quant=next(root.glob("*.csv")))
wb = load_workbook(xlsx); ws = wb.worksheets[0]
heads = [cell.value for cell in ws[1]]
ws.cell(row=1, column=len(heads) + 1, value="density")
ws.cell(row=1, column=len(heads) + 2, value="hardness")
for r in range(2, ws.max_row + 1):
    ws.cell(row=r, column=len(heads) + 1, value=4.4 + r / 1000)
    ws.cell(row=r, column=len(heads) + 2, value=300 + r)
wb.save(xlsx)
ids = [ws.cell(row=r, column=heads.index("part_id") + 1).value for r in range(2, ws.max_row + 1)]
assert ids[0] == "1" and str(s.result.df[pid].drop_nulls()[0]).startswith("Part("), (ids[:3], s.result.df[pid][:3])
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (str(xlsx), ""))

def run_dialog(drive):
    """Open Add from Excel; ``drive(dlg)`` fills it and returns True to accept."""
    real = excel_dialog.ExcelImportDialog.exec
    def exec_(dlg):
        dlg._browse()
        if not drive(dlg):
            return QDialog.DialogCode.Rejected
        dlg._accept()
        return dlg.result()
    excel_dialog.ExcelImportDialog.exec = exec_
    try:
        w._add_excel_column(); drain()
    finally:
        excel_dialog.ExcelImportDialog.exec = real

# 1. Starts on the grid column that holds the keys, and says so.
seen = {}
def check_default(dlg):
    seen["picks"] = (dlg.key_combo.currentText(), dlg.val_combo.currentText(),
                     dlg.name_edit.text())
    seen["grid"] = dlg.gridkey_combo.currentText()
    seen["label"] = dlg.match_label.text()
    # 2. Start time instead: red, and asked before adding an empty column.
    dlg.gridkey_combo.setCurrentText("Start time"); dlg._on_grid_picked(0)
    seen["wrong"] = dlg.match_label.text()
    dlg._accept()
    seen["accepted_wrong"] = dlg.result_values() is not None
    dlg.gridkey_combo.setCurrentText(pid)     # back to the right one
    return True
run_dialog(check_default)
n = len(set(ids))
assert seen["picks"] == ("part_id", "density", "density"), seen["picks"]
assert seen["grid"] == pid, seen
assert seen["label"] == f"{n} of {n} keys match.", seen["label"]
assert seen["wrong"] == f"No keys match. Try {pid!r} ({n} of {n}).", seen["wrong"]
assert asked and asked[0][0] == "No keys match" and not seen["accepted_wrong"], asked
col = s.result.df["density"]
assert col.null_count() == s.result.df[pid].null_count(), "every row with a part has a density"
status = w._log.text()
assert status == (f"Added 'density' from Excel: {s.result.df.height - col.null_count():,} "
                  f"of {s.result.df.height:,} rows have a value."), status
print(f"template part ids ('1') match the grid's ('Part(1)'); default {pid}; {status}")

# 3. "Add anyway" on Start time: added, and the status says it's empty and why.
answer[0] = True; asked.clear()
def wrong_anyway(dlg):
    seen["next"] = (dlg.key_combo.currentText(), dlg.val_combo.currentText(),
                    dlg.name_edit.text())
    dlg.gridkey_combo.setCurrentText("Start time"); dlg._on_grid_picked(0)
    return True
run_dialog(wrong_anyway)
assert seen["next"] == ("part_id", "hardness", "hardness"), "the next measurement"
assert asked and s.result.df["hardness"].null_count() == s.result.df.height
assert w._log.text() == ("Added 'hardness' from Excel, but no keys match 'Start time': "
                         "undo and match on another column."), w._log.text()
print("an empty import is only made after asking, and the status says why")

# 4. Everything imported: density again, under a new name.
def again(dlg):
    seen["again"] = (dlg.val_combo.currentText(), dlg.name_edit.text())
    return False
run_dialog(again)
assert seen["again"] == ("density", "density 2"), seen["again"]

# 5. A plain workbook (no shading): a constant first column, part names in
# "Part ID", coordinates, a grid column, a note and a measurement.
from openpyxl import Workbook
plain = _harness.ROOT / "plain.xlsx"
wb = Workbook(); ws = wb.active
ws.append(["Operator", "Part ID", "x_min", "Start time", "Notes", "Roughness Ra"])
for i, part in enumerate(sorted(set(ids), key=int)):
    ws.append(["AB", f"Part({part})", -i / 3, 1000 + i, f"note {i}", 3 + i / 10])
wb.save(plain)
assert "Start time" in s.result.df.columns, "a grid column"
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (str(plain), ""))
def plain_picks(dlg):
    seen["plain"] = (dlg.key_combo.currentText(), dlg.val_combo.currentText(),
                     dlg.gridkey_combo.currentText())
    return False
run_dialog(plain_picks)
assert seen["plain"] == ("Part ID", "Roughness Ra", pid), seen["plain"]
print("opens on the right key, value and grid column, template or not")

# 6. A column imported before (keys "Part(N)") still matches.
assert derive.norm_key("Part(7)") == derive.norm_key("7") == "7"
w._run("excel_import", name="old", key=pid, mapping={"Part(1)": 1.0, "Part(2)": 2.0}, dtype="f64"); drain()
assert s.result.df.filter(s.result.df[pid] == "Part(1)")["old"].drop_nulls().to_list()[:1] == [1.0]
print("ALL OK")
c.shutdown()
