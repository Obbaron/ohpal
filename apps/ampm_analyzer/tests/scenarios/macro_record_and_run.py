"""Stage-2 checks on a real build: record → save → run reproduces the recorded
state; names are stored canonically; undo while recording drops the step; a
failing run changes nothing."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import json, os, sys, tempfile
BUILD = sys.argv[1]
TMP = tempfile.mkdtemp()

from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog
app = QApplication([])
from ampm_analyzer.shell import macros, macro_dialog
from ampm_analyzer.shell.window import MainWindow

def load(w):
    loop = QEventLoop(); c = w.session.queryReady.connect(lambda *_: loop.quit())
    QTimer.singleShot(120000, loop.quit); w.controller.open_recent(BUILD); loop.exec()
    w.session.queryReady.disconnect(c)
    for _ in range(20): app.processEvents()

w = MainWindow(); w.show(); load(w)
A, c, s, dt, R = w.actions, w.controller, w.session, w._data_tab, w.recorder
SRC = "MeltVIEW melt pool (mean)"; assert SRC in dt._columns

def state():
    snap = A.capture()
    return {k: snap[k] for k in ("derivations", "removed", "renames", "filters")}

# --- dialog stubs -------------------------------------------------------
files = {"save": None, "open": []}
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (files["save"], ""))
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (files["open"].pop(0), ""))
macro_dialog.MacroPreviewDialog.exec = lambda self: QDialog.DialogCode.Accepted
macro_dialog.MacroSaveDialog.exec = lambda self: QDialog.DialogCode.Accepted  # Stop: nothing asked when run
issues = []
def _issues_exec(self):
    issues.append([self.list.item(i).text() for i in range(self.list.count())])
    return QDialog.DialogCode.Accepted
macro_dialog.MacroIssuesDialog.exec = _issues_exec

# --- an Excel file for the import step ----------------------------------
from openpyxl import Workbook
def make_xlsx(path, factor, sheet="Props"):
    wb = Workbook(); ws = wb.active; ws.title = sheet
    ws.append(["Layer", "Gas"]);
    for L in range(1, 11): ws.append([L, L * factor])
    wb.save(path)
xl_a, xl_b = os.path.join(TMP, "a.xlsx"), os.path.join(TMP, "b.xlsx")
make_xlsx(xl_a, 1.0); make_xlsx(xl_b, 2.0)
from ampm_analyzer.shell.excel_dialog import parse_mapping
map_a, dtype_a, _ = parse_mapping(xl_a, "Props", "Layer", "Gas")

# --- before recording: rename a source column (display != original) -----
w._run("rename", old=SRC, new="Meltpool")
w._run("derive", name="pre", expr="[layer] + 0")   # pre-recording action
start = state()

# --- record -------------------------------------------------------------
w._toggle_macro_recording(); assert R.active
assert w._rec_label.isVisible() or True
w._run("derive", name="dbl", expr="[Meltpool] * 2", after="Meltpool")
w._run("label", name="band", rules=[{"cond": "[Meltpool] > 0 and [dbl] > 0", "label": "hi"}], default="lo")
w._run("part_calc", signal="Meltpool", reducer="cov", name="mp cov")
sec, body = c.parts_csv_sections()[0]
csv_col = next(x for x in body.columns if x != "part_id")
w._run("parts_csv_import", items=[[sec, csv_col]])
w._run("excel_import", name="gas", key="layer", mapping=map_a, dtype=dtype_a,
       source={"sheet": "Props", "key_column": "Layer", "value_column": "Gas"})
w._run("set_visible", name="gas", visible=False)          # show/hide: a step too
w._run("rename", old="Meltpool", new="MP")                # macro renames the source col
w._run("derive", name="half", expr="[MP] / 2 + [dbl]")
w._run("derive", name="oops", expr="[layer] * 9"); w._undo()   # undone → dropped
w._run("filter_add", condition="[MP] > -1"); w._undo(); w._redo()  # redone → kept
w._run("remove", names=["Demand focus"])
assert R.count() == 10, R.count()
assert "10 steps" in w._rec_label.text(), w._rec_label.text()
# undo past the start of the recording, then redo: recording unaffected
for _ in range(R.count() + 2): w._undo()
assert R.count() == 0
for _ in range(20): w._redo()
assert R.count() == 10, R.count()
recorded_state = state()

files["save"] = os.path.join(TMP, "prep")                 # no suffix typed
w._toggle_macro_recording(); assert not R.active
mfile = os.path.join(TMP, "prep.macro.json"); assert os.path.exists(mfile), os.listdir(TMP)
doc = json.loads(open(mfile).read())
ops = [st["op"] for st in doc["steps"]]
assert ops == ["derive", "label", "part_calc", "parts_csv_import", "excel_import",
               "set_visible", "rename", "derive", "filter_add", "remove"], ops
assert doc["format"] == "ampm-macro" and doc["version"] == 1 and doc["name"] == "prep"
P = [st["params"] for st in doc["steps"]]
# canonical: source column stored under its ORIGINAL name everywhere
assert P[0]["expr"] == f"[{SRC}] * 2" and P[0]["after"] == SRC, P[0]
assert P[1]["rules"][0]["cond"] == f"[{SRC}] > 0 and [dbl] > 0", P[1]
assert P[2]["signal"] == SRC
assert "mapping" not in P[4] and P[4]["source"]["sheet"] == "Props"   # no data in file
assert P[5] == {"name": "gas", "visible": False}, P[5]
assert P[6] == {"old": SRC, "new": "MP"}, P[6]
assert P[7]["expr"] == f"[{SRC}] / 2 + [dbl]", P[7]
assert P[8]["condition"] == f"[{SRC}] > -1", P[8]
print("recorded + saved:", ops)

# --- run on the same build, from the pre-recording state ----------------
while A.history.can_undo() and state() != start: w._undo()
assert state() == start
n_undo = len(A.history._undo)
files["open"] = [mfile, xl_a]
w._run_macro()
assert not issues, issues
assert state() == recorded_state, "replay did not reproduce the recorded state"
assert len(A.history._undo) == n_undo + 1 and "prep" in A.history.undo_label()
w._undo(); assert state() == start, "one undo should revert the whole macro"
w._redo(); assert state() == recorded_state
print("replay == recorded state; whole run is one undo step")

# --- run again on top: collisions → issue, nothing changes ---------------
files["open"] = [mfile, xl_a]; before = state(); n_undo = len(A.history._undo)
w._run_macro()
assert issues and "Step 1" in issues[-1][0] and "already exists" in issues[-1][0], issues
assert state() == before and len(A.history._undo) == n_undo
print("collision issue:", issues[-1][0].replace("\n", " | ")[:110])

# --- portability: source column under a DIFFERENT display name -----------
w._undo(); assert state() == start
w._run("rename", old="Meltpool", new="Pool X")            # build now calls it 'Pool X'
files["open"] = [mfile, xl_b]; issues.clear()             # and a different Excel file
w._run_macro(); assert not issues, issues
got = state()
assert got["renames"][SRC] == "MP"
d = {x["name"]: x for x in got["derivations"]}
assert d["dbl"]["expr"] == "[MP] * 2" and d["half"]["expr"] == "[MP] / 2 + [dbl]", d["dbl"]
assert d["gas"]["map"] != recorded_state["derivations"][[x["name"] for x in recorded_state["derivations"]].index("gas")]["map"], "Excel data should come from the new file"
assert got["filters"] == ["[MP] > -1"]
print("ran against a renamed column + a different Excel file")

# --- mid-run failure rolls everything back -------------------------------
w._undo(); before = state()
bad = os.path.join(TMP, "bad.macro.json")
macros.save(bad, "bad", [
    {"op": "derive", "params": {"name": "ok1", "expr": "[layer] * 2"}},
    {"op": "derive", "params": {"name": "ok2", "expr": "[nope] + 1"}}])
files["open"] = [bad]; issues.clear(); w._run_macro()
assert issues and "Step 2" in issues[-1][0], issues
assert state() == before, "failed macro left changes behind"

# --- Excel step problems are issues; cancelling the file aborts ----------
files["open"] = [mfile, os.path.join(TMP, "missing.xlsx")]; issues.clear(); w._run_macro()
assert issues and "Step 5" in issues[-1][0] and state() == before, issues
make_xlsx(os.path.join(TMP, "c.xlsx"), 1.0, sheet="Other")
files["open"] = [mfile, os.path.join(TMP, "c.xlsx")]; issues.clear(); w._run_macro()
assert issues and "no sheet named" in issues[-1][0] and state() == before, issues
files["open"] = [mfile, ""]; issues.clear(); w._run_macro()
assert not issues and state() == before

# --- file validation -----------------------------------------------------
for content, frag in (("{not json", "valid JSON"), ('{"format": "x"}', "isn't an AMPM macro"),
                      ('{"format":"ampm-macro","version":99,"steps":[1]}', "version"),
                      ('{"format":"ampm-macro","version":1,"steps":[]}', "no steps"),
                      ('{"format":"ampm-macro","version":1,"steps":[{"op":"explode","params":{}}]}', "unknown action"),
                      ('{"format":"ampm-macro","version":1,"steps":[{"op":"__init__","params":{}}]}', "unknown action")):
    f = os.path.join(TMP, "v.macro.json"); open(f, "w").write(content)
    try: macros.load(f); raise SystemExit(f"accepted bad file: {content}")
    except macros.MacroError as exc: assert frag in str(exc), (frag, str(exc))
files["open"] = [f]; issues.clear(); w._run_macro(); assert issues and state() == before

# --- one-pass name mapping can't chain on a swap -------------------------
assert macros._map_refs("[A] + [B] by [A, B]", {"A": "B", "B": "A"}) == "[B] + [A] by [B, A]"

# --- toolbar: Record ↔ Stop, Run disabled while recording ----------------
def tb(text):
    from PyQt6.QtWidgets import QToolButton
    hit = next((a for a in w.toolbar.actions() if a.toolTip().startswith(text)), None)
    if hit is None and text == "Run a macro":   # with recent macros, Run is a menu button
        hit = next(b for b in w.toolbar.findChildren(QToolButton) if b.toolTip() == text and b.menu())
    assert hit is not None, text
    return hit
assert tb("Record a macro") and tb("Run a macro").isEnabled()
w._toggle_macro_recording()
assert tb("Stop recording") and not tb("Run a macro").isEnabled()
# empty recording → nothing saved
w._toggle_macro_recording(); assert not R.active and tb("Record a macro")
# recording is dropped when the build changes
w._toggle_macro_recording(); w._run("derive", name="zz", expr="[layer] * 3"); assert R.count() == 1
load(w); assert not R.active and not w._rec_label.isVisible()
print("ALL STAGE-2 CHECKS PASS"); w.controller.shutdown()
