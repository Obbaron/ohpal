"""Stage-1 checks on a real build: every action is one undo step, undo restores
the exact prior state, redo re-applies it, failures roll back."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import sys, types
BUILD = sys.argv[1]

from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from ampm_viewer.shell.window import MainWindow
from ampm_viewer.shell.plotspec import PlotSpec

w = MainWindow(); w.show()
loop = QEventLoop()
w.session.queryReady.connect(lambda *_: loop.quit())
w.session.loadFailed.connect(lambda m: (print("LOAD FAILED", m), loop.quit()))
w.session.setupRequired.connect(lambda *_: (print("SETUP REQUIRED"), loop.quit()))
QTimer.singleShot(120000, loop.quit)
w.controller.open_recent(BUILD)
loop.exec()
assert w.session.result is not None, "build did not load to a grid"
A, c, s, dt = w.actions, w.controller, w.session, w._data_tab
for _ in range(20): app.processEvents()
print("loaded:", len(dt._columns), "cols; part assignment:", c.has_part_assignment())

def full():
    """Everything undo must put back: state + the grid's actual columns/hidden."""
    snap = A.capture()
    return ({k: snap[k] for k in ("derivations","removed","renames","filters","hidden")},
            list(dt._columns), sorted(dt.hidden_columns()), list(dt.layout_names()[1]))

checked = 0
def check(op, expect_ok=True, **params):
    """Run → changed; undo → identical to before; redo → identical to after."""
    global checked
    n = len(A.history._undo)
    before = full()
    out = w._run(op, **params)
    assert out.ok == expect_ok, (op, out)
    after = full()
    assert after[0] != before[0], f"{op}: nothing changed"
    assert len(A.history._undo) == n + 1, f"{op}: expected exactly one undo step"
    w._undo()
    got = full()
    assert got == before, f"{op}: undo mismatch\n{got}\n!=\n{before}"
    w._redo()
    got = full()
    assert got == after, f"{op}: redo mismatch\n{got}\n!=\n{after}"
    checked += 1
    return out

cols = list(dt._columns)
num = next(x for x in ("Meltpool", "MeltVIEW melt pool (mean)", "Plasma") if x in cols)
xcol = "X" if "X" in cols else "Demand X"
pid = c.part_id_display()
print("signal:", num, "| x:", xcol, "| pid:", pid)

# a live plot stub so rename's plot-spec rewrite is exercised
plot = types.SimpleNamespace(spec=PlotSpec(kind="2D Scatter", x=xcol, y=num),
                             context=None, raw=None, row_filter=[])
w._plot_tabs.append(plot)

check("derive", name="dbl", expr=f"[{num}] * 2", after=xcol)
order = dt.layout_names()[1]
assert order.index("dbl") == order.index(xcol) + 1, "derive 'after' placement lost on redo"
check("label", name="band", rules=[{"cond": f"[{num}] > 0", "label": "hi"}], default="lo")
check("excel_import", name="xl", key="layer", mapping={"1": 3.5}, dtype="f64")
check("part_calc", signal=num, reducer="mean", name="pm")
n0 = len(s.derivations)
check("part_calc", signal=num, reducer="cov", name="pcov")
assert len(s.derivations) == n0 + 3, "CoV should add mean/std/ratio"
secs = c.parts_csv_sections()
sec, body = secs[0]
item = [sec, next(x for x in body.columns if x != "part_id")]
out = check("parts_csv_import", items=[item]); print(" parts csv:", out.message[:70])

# rename a source column: position must not move, plot spec follows, undo reverts both
pos = dt.layout_names()[1].index(num)
check("rename", old=num, new="MP2")
assert dt.layout_names()[1].index("MP2") == pos, "rename moved the column"
assert plot.spec.y == "MP2", plot.spec
w._undo(); assert plot.spec.y == num and dt.layout_names()[1].index(num) == pos
w._redo(); assert plot.spec.y == "MP2"
check("rename", old="dbl", new="dbl2")           # derived column
assert any("[MP2]" in d.get("expr", "") for d in s.derivations), "refs not rewritten"

# remove a source column from the middle: undo puts it back in the same place
from ampm_viewer.shell.datastore_settings import REQUIRED_COLUMNS
victim = next(x for x in dt.layout_names()[1][2:]
              if x in cols and x not in REQUIRED_COLUMNS and x not in (pid, num))
print(" remove victim:", victim)
vpos = dt.layout_names()[1].index(victim)
check("remove", names=[victim, "band"])
w._undo(); assert dt.layout_names()[1].index(victim) == vpos, "undo didn't restore position"
w._redo()
check("restore", name=victim)
check("set_visible", name="xl", visible=False)
assert "xl" in dt.hidden_columns()
check("filter_add", condition=f"[layer] >= 1")
check("filter_add", condition=f"[MP2] > 0")
check("filter_edit", index=0, condition="[layer] >= 0")
check("filter_remove", index=1)
check("filter_remove_last")
w._run("filter_add", condition="[layer] >= 1")
check("filter_reset")

# required column can't be removed: no change, no undo step, reported
n = len(A.history._undo); b = full()
out = w._run("remove", names=[xcol]); assert not out.ok and "required" in out.message
assert full() == b and len(A.history._undo) == n

# validation failure: no change, no step
out = w._run("derive", name="bad", expr="[nope] + 1"); assert not out.ok
assert full() == b and len(A.history._undo) == n

# half-applied composite rolls back completely (fail the 3rd add of a CoV)
real = c.add_derivation; calls = {"n": 0}
def flaky(*a, **k):
    calls["n"] += 1
    return "boom" if calls["n"] == 3 else real(*a, **k)
c.add_derivation = flaky
out = w._run("part_calc", signal="xl", reducer="cov", name="xcov")
c.add_derivation = real
assert not out.ok and calls["n"] == 3, out
assert full() == b and len(A.history._undo) == n, "partial CoV was not rolled back"

# a new action clears redo; undo-all returns to the freshly loaded state
w._undo(); assert A.history.can_redo()
w._run("filter_add", condition="[layer] >= 1"); assert not A.history.can_redo()
while A.history.can_undo(): w._undo()
f0 = full()
assert not any(d["name"] in ("dbl","dbl2","band","xl","pm","pcov") for d in s.derivations)
print("undo-all → derivations:", len(s.derivations), "filters:", c.filters())
while A.history.can_redo(): w._redo()
assert "pcov" in dt._columns and "dbl2" in dt._columns

# buttons + tooltips
ub, rb = w._global_btns["undo"], w._global_btns["redo"]
assert ub.isEnabled() and not rb.isEnabled() and "Undo:" in ub.toolTip(), ub.toolTip()

# undo from another tab re-shapes quietly (no jump to the Data tab)
w.tabbar.setCurrentIndex(0); w._undo(); assert w.tabbar.currentIndex() == 0
w._redo(); w.tabbar.setCurrentIndex(1)

# persisted file matches live state after undo/redo
from ampm_viewer.shell import uistate
st = uistate.load_state(w._grid_cache_dir)
assert st["derivations"] == s.derivations and st["renames"] == s.renames

# bounded history
from ampm_viewer.shell.history import History
h = History(limit=3)
for i in range(5): h.push(str(i), {}, {})
assert len(h._undo) == 3 and h.undo_label() == "4"

# history is per build: cleared on reload
loop2 = QEventLoop(); w.session.queryReady.connect(lambda *_: loop2.quit())
QTimer.singleShot(120000, loop2.quit)
w.controller.open_recent(BUILD); loop2.exec()
assert not A.history.can_undo() and not A.history.can_redo()
print(f"ALL STAGE-1 CHECKS PASS ({checked} action round-trips)")
w.controller.shutdown()
