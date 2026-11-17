"""Macros, the finishing touches: show/hide recorded; a plot's toolbar options
recorded (across pop-out and dock-in); values asked for when run (chosen on
Stop); a column the build lacks swapped for one of its own."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import json, os, sys, tempfile, time
BUILD = sys.argv[1]
TMP = tempfile.mkdtemp()

from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication, QDialog, QFileDialog
app = QApplication([])
from ampm_viewer.shell import controller as cmod, macro_dialog, macros, plot_dialog
from ampm_viewer.shell.plotspec import BAR, default_spec
from ampm_viewer.shell.window import MainWindow

cmod._tell = lambda *a, **k: None
w = MainWindow(); w.resize(1200, 760); w.show()
c, s, R = w.controller, w.session, w.recorder

def drain(limit=120):
    t0 = time.time()
    while time.time() - t0 < limit:
        app.processEvents()
        if not c._queue and c._current is None and not c._busy:
            for _ in range(30): app.processEvents(); time.sleep(0.005)
            if not c._queue and c._current is None: return
        time.sleep(0.02)
loop = QEventLoop(); s.queryReady.connect(lambda *_: loop.quit()); QTimer.singleShot(120000, loop.quit)
c.open_recent(BUILD); loop.exec(); drain()
SRC = next(n for n in s.result.df.columns if "elt" in n and "ool" in n)
statuses = []; real_status = w.set_status
w.set_status = lambda t, *a, **k: (statuses.append(t), real_status(t, *a, **k))

# --- the pieces --------------------------------------------------------
assert macros.references("derive", {"name": "n", "expr": "[a] + [b]", "group": "g"}) == ["g", "a", "b"]
assert macros.references("label", {"name": "n", "rules": [{"cond": "[x] > 1"}]}) == ["x"]
assert macros.references("plot", {"spec": {"x": "p", "y": "q", "color": None}, "span": ["all"]}) == ["p", "q"]
assert macros.references("set_visible", {"name": "h", "visible": False}) == ["h"]
sub = macros.substitute([{"op": "derive", "params": {"name": "n", "expr": "[a] * 2"}}], {"a": "z"})
assert sub[0]["params"]["expr"] == "[z] * 2"
assert [f for f, _ in macros.promptable("label", {"name": "b", "rules": [{"cond": "1"}, {"cond": "2"}]})] == ["rules.0.cond", "rules.1.cond"]
bad = os.path.join(TMP, "bad.macro.json")
open(bad, "w").write(json.dumps({"format": "ampm-macro", "version": 1, "steps": [
    {"op": "filter_add", "params": {"condition": "[layer] > 0"}, "ask": ["expr"]}]}))
try: macros.load(bad); raise SystemExit("accepted an ask for a field the step doesn't have")
except macros.MacroError as exc: assert "asks for values" in str(exc)
print("references / substitute / promptable / ask validation")

# --- record: hide a column, a filter, a plot whose options then change ----
class FakePlotDialog:
    def __init__(self, kind, *a, **k): self.kind = kind
    def exec(self): return QDialog.DialogCode.Accepted
    def spec(self): return default_spec(BAR, list(s.result.df.columns), s.renames)
    def span(self): return ("all", None, None)
plot_dialog.NewPlotDialog = FakePlotDialog

w._toggle_macro_recording(); assert R.active
HIDE = "Demand X"
assert HIDE not in w._data_tab.hidden_columns()
w._run("set_visible", name=HIDE, visible=False)
w._run("filter_add", condition=f"[{SRC}] > 0")
w._new_plot(BAR); drain()
tab = w._active_plot
assert R.steps()[-1]["op"] == "plot" and R.steps()[-1]["params"]["spec"]["sort"] == "name"
tab.set_control("sort", "value"); drain()
assert R.steps()[-1]["params"]["spec"]["sort"] == "value", "the option change reached the step"
assert any("keeps this plot's new setting" in t for t in statuses)
w._popout_plot(); drain(); win = w._detached[-1]
win._tab.set_control("sort", "name"); drain()
assert R.steps()[-1]["params"]["spec"]["sort"] == "name", "followed into the floating window"
w._dock_plot(win); drain(); docked = w._active_plot
docked.set_control("sort", "value"); drain()
assert R.steps()[-1]["params"]["spec"]["sort"] == "value", "and back after docking"
ops = [st["op"] for st in R.steps()]
assert ops == ["set_visible", "filter_add", "plot"], ops
print("recorded:", ops, "| plot step follows its options:", R.steps()[-1]["params"]["spec"]["sort"])

# --- Stop: tick the filter condition and the plot's layers to be asked -----
seen_items = []
def tick_some(self):
    seen_items.extend((i, f) for i, f, _box in self._boxes)
    for i, f, box in self._boxes:
        box.setChecked(f in ("condition", "span"))
    return QDialog.DialogCode.Accepted
macro_dialog.MacroSaveDialog.exec = tick_some
mfile = os.path.join(TMP, "asks.macro.json")
QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (mfile, ""))
w._toggle_macro_recording(); assert not R.active and os.path.exists(mfile)
assert seen_items == [(1, "condition"), (2, "span")], seen_items   # show/hide: nothing to ask
doc = json.loads(open(mfile, encoding="utf-8").read())
assert [st.get("ask") for st in doc["steps"]] == [None, ["condition"], ["span"]], doc["steps"]
assert doc["steps"][2]["params"]["spec"]["sort"] == "value"
print("saved with asks:", [st.get("ask") for st in doc["steps"]])

# --- run it: the inputs card asks, the answers are used --------------------
while w.actions.history.can_undo(): w._undo()
for t in list(w._plot_tabs): w._close_plot(t)
drain(); assert HIDE not in w._data_tab.hidden_columns() and c.filters() == []
macro_dialog.MacroPreviewDialog.exec = lambda self: QDialog.DialogCode.Accepted
asked = {}
def answer(self):
    for key, (kind, editor) in self._editors.items():
        asked[key] = kind
        if kind == "span":
            editor.mode.setCurrentIndex(editor.mode.findData("range"))
            editor.lo.setValue(2); editor.hi.setValue(4)
        else:
            assert editor.text() == f"[{SRC}] > 0", editor.text()   # recorded value shown
            editor.setText(f"[{SRC}] > 100")
    return QDialog.DialogCode.Accepted
macro_dialog.MacroInputsDialog.exec = answer
w._run_macro(mfile); drain()
assert asked == {"1:condition": "text", "2:span": "span"}, asked
assert c.filters() == [f"[{SRC}] > 100"], c.filters()
plot = w._active_plot
assert plot is not None and tuple(plot.span) == ("range", 2, 4), plot.span
assert plot.spec.sort == "value", "the recorded option replays"
assert HIDE in w._data_tab.hidden_columns(), "the hide step replays"
print("run: asked", sorted(asked), "→ filter", c.filters(), "plot span", plot.span)

# cancelling the inputs changes nothing
while w.actions.history.can_undo(): w._undo()
macro_dialog.MacroInputsDialog.exec = lambda self: QDialog.DialogCode.Rejected
n_plots = len(w._plot_tabs); w._run_macro(mfile); drain()
assert c.filters() == [] and len(w._plot_tabs) == n_plots and statuses[-1] == "Macro cancelled."

# --- a column this build doesn't have: pick a substitute -------------------
other = os.path.join(TMP, "other.macro.json")
macros.save(other, "other", [
    {"op": "derive", "params": {"name": "twice", "expr": "[Pool signal] * 2"}},
    {"op": "plot", "params": {"spec": {**default_spec(BAR, list(s.result.df.columns), s.renames).__dict__,
                                       "y": "Pool signal"}, "span": ["all", None, None]}},
])
pick = {}
def choose(self):
    pick["missing"] = list(self._pickers)
    pick["ok_before"] = self.ok_button.isEnabled()
    combo = self._pickers["Pool signal"]
    combo.setCurrentIndex(combo.findText(SRC))
    pick["ok_after"] = self.ok_button.isEnabled()
    pick["ok_text"] = self.ok_button.text()
    return QDialog.DialogCode.Accepted
macro_dialog.MacroIssuesDialog.exec = choose
w._run_macro(other); drain()
assert pick["missing"] == ["Pool signal"] and pick["ok_text"] == "Check again", pick
assert not pick["ok_before"] and pick["ok_after"], "OK waits for a choice"
df = s.result.df
assert "twice" in df.columns and (df["twice"] == df[SRC] * 2).all()
assert w._active_plot.spec.y == SRC
assert f"Used '{SRC}' for 'Pool signal'" in statuses[-1], statuses[-1]
assert json.loads(open(other, encoding="utf-8").read())["steps"][0]["params"]["expr"] == "[Pool signal] * 2", \
    "the file isn't changed"
print("substitute:", statuses[-1])

# cancelling the picker changes nothing
while w.actions.history.can_undo(): w._undo()
macro_dialog.MacroIssuesDialog.exec = lambda self: QDialog.DialogCode.Rejected
w._run_macro(other); drain()
assert "twice" not in s.result.df.columns and "was not run" in statuses[-1]
c.shutdown()
print("MACRO INPUTS AND SUBSTITUTES CHECKS PASS")
