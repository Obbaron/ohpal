"""A rebuild is a clean slate; the grid lands on a layer that has data (mask arriving mid-query, reopen with a mask, layers not built)."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import os, sys
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication
from shapely.geometry import box
app = QApplication([])
from ampm_viewer.shell import uistate
from ampm_viewer.shell.window import MainWindow
BUILD = sys.argv[1]

def wait(w, kick):
    loop = QEventLoop(); c = w.session.queryReady.connect(lambda *_: loop.quit())
    QTimer.singleShot(180000, loop.quit); kick(); loop.exec(); w.session.queryReady.disconnect(c)
    for _ in range(30): app.processEvents()

w = MainWindow(); w.show()
wait(w, lambda: w.controller.open_recent(BUILD))
c, s, dt = w.controller, w.session, w._data_tab
cache = w._grid_cache_dir

# ---------- 1. rebuild = clean slate ------------------------------------
fresh_cols, fresh_hidden = list(dt._columns), sorted(dt.hidden_columns())
victim = "Demand focus"; assert victim in dt._columns
w._run("derive", name="dbl", expr="[layer] * 2")
w._run("remove", names=[victim])
w._run("set_visible", name="Z", visible=False)
assert "Z" in dt.hidden_columns()
w._run("filter_add", condition="[layer] >= 1")
dt.set_column_sigfigs("Z", 9)
assert s.derivations and s.removed and c.filters() and w.actions.history.can_undo()
assert uistate.load_state(cache)["removed"] == [victim]

form = w.backstage.ds_form
form.chk_mask.setChecked(False)
for row in form._col_rows:                 # rebuild asking for every column
    row.set_state(included=True, rename="Xpos" if row.name == "Demand X" else "")
recipe_cols = set(form.columns())
wait(w, w._on_build_requested)
dt = w._data_tab
assert s.derivations == [] and s.removed == [] and c.filters() == [], (s.derivations, s.removed, c.filters())
assert not w.actions.history.can_undo() and not w.actions.history.can_redo()
assert victim in dt._columns, "a removed column must load again after a rebuild"
assert "dbl" not in dt._columns
from ampm_viewer.shell.data_tab import DEFAULT_HIDDEN
assert set(dt.hidden_columns()) == DEFAULT_HIDDEN & set(dt._columns), dt.hidden_columns()
assert dt.model.sigfigs("Z") == 4, "display settings should reset"
shown = {s.renames and {v: k for k, v in s.renames.items()}.get(x, x) for x in dt._columns}
missing = recipe_cols - shown
assert not missing, f"recipe columns not loaded: {missing}"
st = uistate.load_state(cache)
assert st["derivations"] == [] and st["removed"] == [] and st["filters"] == []
assert st["renames"] == {"Demand X": "Xpos"} == s.renames, st["renames"]
assert "Xpos" in dt._columns
print("rebuild: clean slate (columns, hidden, filters, derived, sig figs, history, saved file)")

# ---------- 2. landing layer ---------------------------------------------
layers = list(s.store.layers); print("store layers:", layers)
assert s.current_layer == layers[0]
big = box(-1e6, -1e6, 1e6, 1e6)

# 2a. mask arrives while the layer-1 query is in flight -> lands on lowest masked layer
c._apply_mask = True; c._mask_geom = None
def race():
    c._request((layers[0], layers[0]), c._deliver_grid, "layer", coalesce=True)
    c._on_mask_done({L: big for L in layers[3:]}, "k")     # layers 1-3 have no part
wait(w, race)
assert s.current_layer == layers[3], s.current_layer
assert s.result.df.height > 0
print("mask arriving mid-query: landed on layer", s.current_layer)

# 2b. reopening from cache with the mask already known lands on the lowest masked layer
uistate.set_apply_mask(cache, True)
real_ensure = c._ensure_mask
def fake_ensure():
    if c._apply_mask: c._mask_geom, c._mask_key = {L: big for L in layers[2:]}, "k"
c._ensure_mask = fake_ensure
wait(w, lambda: c.open_recent(BUILD))
assert s.current_layer == layers[2], s.current_layer
print("reopen with mask: landed on layer", s.current_layer)

# 2c. no mask, lowest layers not in the DataStore: land on the lowest built layer,
#     without converting layer 1 just to show it
uistate.set_apply_mask(cache, False); c._ensure_mask = real_ensure
for L in layers[:2]: os.remove(s.store._cache_path(L))
wait(w, lambda: c.open_recent(BUILD))
assert s.current_layer == layers[2], s.current_layer
assert not os.path.exists(s.store._cache_path(layers[0])), "layer 1 was built just to land on it"
print("reopen with layers 1-2 not built: landed on layer", s.current_layer)
print("ALL REBUILD / LANDING CHECKS PASS")
try: c.shutdown()
except RuntimeError: pass
