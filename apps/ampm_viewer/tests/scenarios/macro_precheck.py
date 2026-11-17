"""Stage-3 checks on a real build: the whole macro is checked before anything
changes, every issue is listed, and a clean check means the run succeeds."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import os, sys, tempfile
BUILD, TMP = sys.argv[1], tempfile.mkdtemp()
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog
app = QApplication([])
from ampm_viewer.shell import macros, macro_dialog
from ampm_viewer.shell.window import MainWindow
w = MainWindow(); w.show()
loop = QEventLoop(); w.session.queryReady.connect(lambda *_: loop.quit()); QTimer.singleShot(120000, loop.quit)
w.controller.open_recent(BUILD); loop.exec()
for _ in range(20): app.processEvents()
A, c, s, dt = w.actions, w.controller, w.session, w._data_tab
SRC = "MeltVIEW melt pool (mean)"
def state():
    snap = A.capture(); return {k: snap[k] for k in ("derivations", "removed", "renames", "filters")}
def step(op, **p): return {"op": op, "params": p}
def check(steps): return A.check_batch([(x["op"], x["params"]) for x in steps], macros.resolve)

files = {"open": []}; previews = []; popups = []
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (files["open"].pop(0), ""))
macro_dialog.MacroPreviewDialog.exec = lambda self: (previews.append(1), QDialog.DialogCode.Accepted)[1]
macro_dialog.MacroIssuesDialog.exec = lambda self: (popups.append(
    [self.list.item(i).text() for i in range(self.list.count())]), QDialog.DialogCode.Accepted)[1]
def run_file(name, steps):
    f = os.path.join(TMP, f"{name}.macro.json"); macros.save(f, name, steps)
    files["open"] = [f]; popups.clear(); previews.clear(); w._run_macro()

sec, body = c.parts_csv_sections()[0]
csv_col = next(x for x in body.columns if x != "part_id")
assert c.assigned_part_ids(), "test build should have a part assignment"
w._run("rename", old=SRC, new="Meltpool")           # display != original on this build
w._run("derive", name="have", expr="[layer] + 0")   # a column the build already has
base = state(); n_undo = len(A.history._undo)

# --- 1. a macro with many problems: ALL listed, nothing changed -----------
bad = [
    step("derive", name="have", expr=f"[{SRC}] * 2"),                     # 1 collision
    step("derive", name="a1", expr="[no such col] + 1"),                  # 2 missing column
    step("derive", name="a2", expr="[a1] * 2"),                           # 3 fine: builds on step 2
    step("label", name="lab", rules=[{"cond": "[ghost] > 1", "label": "x"}]),  # 4 missing column
    step("rename", old="Not There", new="Z2"),                            # 5 missing column
    step("remove", names=["Demand X"]),                                   # 6 required column
    step("restore", name="Demand focus"),                                 # 7 not removed
    step("filter_add", condition="[ghost] > 1"),                          # 8 bad filter
    step("filter_remove", index=5),                                       # 9 no such filter
    step("parts_csv_import", items=[["No Such Section", "X"], [sec, "No Such Col"]]),  # 10 two problems
    step("excel_import", name="xl", key="layer"),                         # 11 no source recorded
    step("part_calc", signal=SRC, reducer="mean", name="pm"),             # 12 fine
    step("filter_add", condition=f"[{SRC}] > 0 and [a2] > 0"),            # 13 fine
]
run_file("bad", bad)
assert len(popups) == 1 and not previews, (len(popups), previews)
items = popups[0]; flagged = [int(x.split()[1]) for x in items]
assert flagged == [1, 2, 4, 5, 6, 7, 8, 9, 10, 11], flagged
assert items[8].count("•") == 2, items[8]                               # step 10: both problems
assert "already exists" in items[0] and "Unknown column: 'no such col'" in items[1]
assert "required" in items[4] and "no section" in items[8] and "has no column" in items[8]
assert state() == base and len(A.history._undo) == n_undo, "pre-check must not change anything"
print("all issues listed in one popup (steps):", flagged)
for x in items[:3] + [items[8]]: print("   ", x.replace("\n", "  "))

# --- 2. mid-macro renames / removals are followed -------------------------
ok = [step("rename", old=SRC, new="MP"),                 # stored by original name
      step("derive", name="d1", expr=f"[{SRC}] * 2"),    # → [MP] at that point
      step("remove", names=["Demand focus"]),
      step("derive", name="d2", expr="[Demand focus] + [d1]"),   # removed cols stay usable in formulas
      step("restore", name="Demand focus"),
      step("filter_add", condition=f"[{SRC}] > 0"),
      step("filter_edit", index=0, condition="[d1] > 0"),
      step("filter_remove_last")]
assert check(ok) == [], check(ok)
got = check([step("remove", names=["Demand focus"]), step("filter_add", condition="[Demand focus] > 0")])
assert [i for i, _ in got] == [1], got     # filtering on a removed column is caught
run_file("ok", ok); assert not popups and previews, popups
assert s.renames[SRC] == "MP" and {"d1", "d2"} <= {d["name"] for d in s.derivations}
w._undo(); assert state() == base
print("renames/removals inside the macro are tracked; clean macro ran as one undo step")

# --- 3. a clean check means the run succeeds; an issue means it didn't run --
cases = [
    [step("derive", name="q1", expr="[layer] * 2"), step("part_calc", signal="q1", reducer="cov", name="q cov")],
    [step("label", name="q2", rules=[{"cond": "[layer] > 2", "label": "hi"}], default="lo")],
    [step("parts_csv_import", items=[[sec, csv_col]])],
    [step("laser_params")],
    [step("remove", names=["Demand focus", "have"]), step("restore", name="Demand focus")],
    [step("filter_add", condition="[layer] > 0"), step("filter_reset")],
    [step("derive", name="have", expr="[layer]", overwrite=True)],
    [step("derive", name="q3", expr="[layer] +")],                 # syntax error
    [step("rename", old="have", new="Meltpool")],                  # collides with a source column
    [step("label", name="q4", rules=[])],
    [step("filter_edit", index=0, condition="[layer] > 0")],       # no filter yet
    [step("part_calc", signal="nope", reducer="mean", name="q5")],
]
agree = 0
for steps in cases:
    found = check(steps)
    failed, msg, _ = A.run_batch("t", [(x["op"], x["params"]) for x in steps],
                                 prepare=lambda op, p: macros.resolve(op, p, s.renames))
    if failed is None and A.history.undo_label() == "t": w._undo()
    assert state() == base, steps
    if not found:
        assert failed is None, f"check passed but run failed: {steps} -> {msg}"
    agree += 1
print(f"check ↔ run agreement on {agree} macros (clean check ⇒ run succeeds)")
clean = sum(1 for steps in cases if not check(steps)); assert clean == 7, clean

# --- 4. part prerequisites and part matching -------------------------------
real_has, real_csv, real_ids = c.has_part_assignment, c.has_laser_parameters, c.assigned_part_ids
parts = [step("part_calc", signal=SRC, reducer="mean", name="pm"), step("laser_params"),
         step("parts_csv_import", items=[[sec, csv_col]])]
c.has_part_assignment = lambda: False
got = check(parts); assert [i for i, _ in got] == [0, 1, 2] and all("no part assignment" in m for _, m in got), got
c.has_part_assignment = real_has; c.has_laser_parameters = lambda: False
got = check(parts); assert [i for i, _ in got] == [1, 2] and all("no parts CSV" in m for _, m in got), got
c.has_laser_parameters = real_csv
c.assigned_part_ids = lambda: {"Widget(1)", "Widget(2)"}          # ids that match nothing
got = check(parts); assert [i for i, _ in got] == [1, 2] and "None of the build's 2 parts" in got[0][1], got
total = len(real_ids())
c.assigned_part_ids = lambda: real_ids() | {"Extra(1)", "Extra(2)"}   # partial match
assert check(parts) == []
run_file("parts", parts); assert not popups
assert f"matched {total} of {total + 2} parts" in w._log._full, w._log._full
w._undo()
out = w._run("parts_csv_import", items=[[sec, csv_col]])
assert f"Matched {total} of {total + 2} parts." in out.message, out.message
w._undo(); c.assigned_part_ids = real_ids
out = w._run("laser_params"); assert f"Matched {total} of {total} parts." in out.message, out.message
print("part prerequisites, zero-match issue and partial-match report:", out.message[-28:])

# laser parameters already present on the build → every clash listed
got = check([step("laser_params")]); assert got and all("already exists" in m for _, m in got), got[:2]
# ...but a macro that adds them itself and then imports an overlapping column is fine
w._undo()
both = [step("laser_params"), step("parts_csv_import", items=[["Scan Volume", "Hatches Power"]])]
if "Scan Volume" in dict(c.parts_csv_sections()): assert check(both) == [], check(both)
# hand-edited step with wrong settings is an issue, not a crash
got = check([step("derive", nam="x", expr="1")]); assert got and "settings aren't valid" in got[0][1]
print("ALL STAGE-3 CHECKS PASS")
try: c.shutdown()
except RuntimeError: pass
