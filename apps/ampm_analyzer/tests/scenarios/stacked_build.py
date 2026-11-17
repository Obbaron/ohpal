"""A stacked (stepped) build: two step builds read as one. Layers, Z and
Build time carry on across the seam, part ids take the step, each step's own
STL masks its layers, and the stack reopens like a build."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import shutil, sys, tempfile, time
from pathlib import Path
BUILD, TMP = Path(sys.argv[1]), Path(tempfile.mkdtemp())
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import polars as pl
from ampm_analyzer.shell import controller as cmod, stackbuild
from ampm_analyzer.shell.window import MainWindow
told = []
# The test build's STL doesn't reach its first layers: slice to a box that
# holds everything, and note what each step's STL was sliced at.
from ohpal.ampm import masking
from shapely.geometry import box
sliced = []
def fake_mask(stl, layers, layer_thickness=0.03, cache_path=None, **_k):
    sliced.append((Path(stl).parent.name, list(layers), layer_thickness,
                   Path(cache_path).name))
    return {L: box(-1e6, -1e6, 1e6, 1e6) for L in layers}
masking.build_mask = fake_mask
cmod._tell = lambda parent, title, text, **k: told.append((title, text))

# -- two steps: the build (layers 1-10) and a copy of its first 4 layers ------
s1 = BUILD
s2 = TMP / "JR299 step 2"
shutil.copytree(BUILD, s2)
packets = next(p for p in s2.iterdir() if p.is_dir() and "Packets" in p.name)
for f in packets.iterdir():
    m = stackbuild._PACKET_RE.match(f.name)
    if m and int(m.group(1)) > 4:
        f.unlink()
for n in range(5, 11):                      # its DataStore: layers 1-4 only
    (packets / ".cache" / f"layer={n:05d}.parquet").unlink(missing_ok=True)

# -- the dialog: steps in order, where their layers land, checks --------------
dlg = stackbuild.NewStackDialog(None, start_dir=str(TMP))
assert dlg.problem() == "A stacked build needs at least two steps."
assert dlg.add_step(s1) is None and dlg.add_step(s2) is None
assert "already a step" in dlg.add_step(s1)
(TMP / "empty").mkdir()
assert "No packet data" in dlg.add_step(TMP / "empty")
rows = [dlg.list.item(i).text() for i in range(dlg.list.count())]
assert "layers 1-10  ->  1-10" in rows[0] and "layers 1-4  ->  11-14" in rows[1], rows
dlg.list.setCurrentRow(1); dlg._move(-1)
assert "->  1-4" in dlg.list.item(0).text(), "moving a step renumbers the stack"
dlg._move(1)
assert dlg.name.text() == f"{s1.name} stacked"
assert Path(dlg.folder.text()) == s1.parent / f"{s1.name} stacked"
dlg.folder.setText(str(s1 / "inside")); assert "outside" in dlg.problem()
stack = TMP / "JR299 stacked"
dlg.folder.setText(str(stack)); dlg.name.setText("JR299 stepped")
assert dlg.problem() is None
dlg._accept()
folder, name, steps = dlg.chosen()
assert folder == stack.resolve() and name == "JR299 stepped" and steps == [s1.resolve(), s2.resolve()]
print("dialog: steps in order with their stacked layers; checks the folder")

# -- open it like a new build: the stack's one setup page -----------------------
w = MainWindow(); w.resize(1300, 760); w.show(); c, s = w.controller, w.session

def wait(sig, kick, limit=240000):
    loop = QEventLoop(); h = sig.connect(lambda *_: loop.quit())
    QTimer.singleShot(limit, loop.quit); kick(); loop.exec(); sig.disconnect(h)
    for _ in range(30): app.processEvents()

def drain(limit=300):
    t0 = time.time()
    while time.time() - t0 < limit:
        app.processEvents()
        if not c._queue and c._current is None and not c._busy and c._mask_thread is None:
            for _ in range(40): app.processEvents()
            return
        time.sleep(0.02)
    raise SystemExit("never went idle")

wait(s.setupRequired, lambda: c._load(stack, "new", stack=(name, steps)))
assert (stack / "stacked.toml").is_file()
store = s.store
assert stackbuild.is_stack(store) and store.layers == list(range(1, 15)), store.layers
assert s.build_name == "JR299 stepped"
f = w.backstage.ds_form
assert f.lbl_source_key.text() == "Steps" and "S2" in f.lbl_source.text()
assert "11-14" in f.lbl_source.text(), f.lbl_source.text()
assert f.lbl_stl.text().startswith("Each step's own"), f.lbl_stl.text()
assert not f.thickness_spin.isEnabled(), "each step keeps its own thickness"
assert not f._part_option_enabled(2), "no DBSCAN across steps"
assert f._part_option_enabled(0), "Direct: every step has a parts CSV"
assert {"step", "Build time"} <= set(f.columns()), "step and Build time come by default"
assert f.chk_mask.isEnabled() and f.chk_mask.isChecked()
f.cmb_parts.setCurrentText("Direct")
wait(s.queryReady, w._on_build_requested); drain()
print("setup: steps listed, thickness per step, no DBSCAN, step + Build time ticked")

# -- the data: layers, Z, step, Build time and part ids carry on ---------------
dt = w._data_tab
assert "step" in dt._columns and "Build time" in dt._columns, dt._columns
df = store.query(layers=(10, 11), columns=["Start time", "Build time", "step", "part_id"])
by = df.group_by("layer").agg(pl.col("step").first(), pl.col("Z").first(),
                              pl.col("Build time").min().alias("t0"),
                              pl.col("Build time").max().alias("t1"),
                              pl.col("part_id").drop_nulls().first())
row = {r["layer"]: r for r in by.iter_rows(named=True)}
assert row[10]["step"] == 1 and row[11]["step"] == 2
th = store.steps[0].thickness
assert abs(row[11]["Z"] - 11 * th) < 1e-5, (row[11]["Z"], th)
assert row[11]["t0"] > row[10]["t1"], "Build time carries on into step 2"
assert row[10]["part_id"].startswith("S1 ") and row[11]["part_id"].startswith("S2 "), row
ids = c.assigned_part_ids()
assert any(i.startswith("S1 ") for i in ids) and any(i.startswith("S2 ") for i in ids)
print("data: layer 10 -> 11 crosses the seam; Z, Build time, step, S1/S2 part ids")

# -- each step's STL masks its own layers --------------------------------------
t0 = time.time()
while c._mask_geom is None and time.time() - t0 < 120:
    app.processEvents(); time.sleep(0.05)
drain()
assert c._mask_geom is not None, "the stack's mask should build"
assert sorted(c._mask_geom) == list(range(1, 15)), sorted(c._mask_geom)
assert sliced == [(s1.name, list(range(1, 11)), 0.03, "mask_S1.pkl"),
                  (s2.name, [1, 2, 3, 4], 0.03, "mask_S2.pkl")], sliced
assert c.available_layers() == list(range(1, 15))
print("mask: each step's STL at its own layers, keyed by stacked layer")

# -- the parts CSV: each step's, with the step on its part ids ----------------
assert c.has_laser_parameters()
lp = c.part_laser_parameters()
pids = lp["part_id"].to_list()
assert any(p.startswith("S1 ") for p in pids) and any(p.startswith("S2 ") for p in pids)
secs = c.parts_csv_sections()
assert secs and all(any(v.startswith("S2 ") for v in b["part_id"].to_list()) for _, b in secs)
print("parts CSV: laser parameters and sections per step:", len(secs), "sections")

# -- reopen: straight to the data, with the setup kept --------------------------
wait(s.queryReady, lambda: c.open_recent(str(stack))); drain()
assert stackbuild.is_stack(s.store) and s.store.layers[-1] == 14
assert "step" in w._data_tab._columns and c.apply_mask()
assert w.windowTitle().endswith("JR299 stepped")
assert s.store.cached_layers() == set(range(1, 15))
assert any(e.path == str(stack) for e in c._recents.load()), "the stack is a recent build"
assert not told, told
print("reopen: from Recent, straight to its data")
w.close()
print("ALL OK")
