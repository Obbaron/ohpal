"""The File tab: New's menu, contextual DataStore / Info / Close, the landing
page and its Recent list (type, status and time in columns; library plots
too), and the setup page: foldable groups, Browse... for each input (kept in
config.toml), All layers / From-To, column buttons, Direct's max distance,
DBSCAN's chunking, the Part filter (kept with the build) and the Info page."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import sys, time
from pathlib import Path
BUILD = Path(sys.argv[1])
from PyQt6.QtCore import QEventLoop, QPointF, Qt, QTimer
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication, QFileDialog
app = QApplication([])
import polars as pl
from ampm_viewer.shell import controller as cmod, uistate
from ampm_viewer.shell.backstage import DATASTORE, INFO, LIBRARY, START
from ampm_viewer.shell.recents import RecentStore, kind_of
from ampm_viewer.shell.window import MainWindow
told = []
cmod._tell = lambda parent, title, text, **k: told.append((title, text))
cmod._ask = lambda parent, title, text, **k: True

def pump(n=30):
    for _ in range(n): app.processEvents()

# -- config.toml: one [paths] entry set, the rest left as it was ---------------
toml = BUILD / "config.toml"
before = toml.read_text(encoding="utf-8")
cmod.write_config_path(BUILD, "DHXML", BUILD / "sub" / "x.dhxml")
after = toml.read_text(encoding="utf-8")
assert "dhxml = \"sub/x.dhxml\"" in after, after
assert sum(ln.strip().startswith("dhxml") for ln in after.splitlines()) == 1
assert [l for l in after.splitlines() if not l.strip().startswith("dhxml")] == \
       [l for l in before.splitlines() if not l.strip().startswith("dhxml")]
toml.write_text(before, encoding="utf-8")
other = Path(_harness.ROOT) / "cfg"; other.mkdir()
(other / "config.toml").write_text("[build]\nlayer_thickness = 0.03\n")
cmod.write_config_path(other, "STL", "/elsewhere/part.stl")
assert "[paths]\nstl = \"/elsewhere/part.stl\"" in (other / "config.toml").read_text()
print("config.toml: one path set in place (relative inside the build), others kept")

w = MainWindow(); w.resize(1300, 800); w.show(); c, s, bs = w.controller, w.session, w.backstage
f = bs.ds_form

# -- sidebar: New is a menu; DataStore / Info / Close only when they apply -------
assert [a.text() for a in bs.new_menu.actions()] == ["Single build", "Stacked build", "Excel template"]
for gone in ("btn_stack", "btn_excel", "btn_export", "tile_open"):
    assert not hasattr(bs, gone), gone
assert bs.btn_datastore.isHidden() and bs.btn_info.isHidden() and bs.btn_close.isHidden()
asked = []
bs.newRequested.disconnect(); bs.stackRequested.disconnect()   # no folder pickers here
bs.newRequested.connect(lambda: asked.append("single"))
bs.stackRequested.connect(lambda: asked.append("stack"))
bs.act_new_single.trigger(); bs.tile_new.click()
bs.act_new_stack.trigger()
assert asked == ["single", "single", "stack"], asked
assert [t.findChildren(type(bs.info_title))[0].text() for t in (bs.tile_new, bs.tile_stack, bs.tile_excel)] \
    == ["Single build", "Stacked build", "Excel template"]
bs.show_library_page(); pump()
assert bs.main_stack.currentIndex() == LIBRARY and not bs.btn_close.isHidden()
bs.btn_close.click(); pump()
assert bs.main_stack.currentIndex() == START and bs.btn_close.isHidden()
print("sidebar: New menu, Close back to the landing page")

# -- open the build: the setup page --------------------------------------------
def wait(kick):
    loop = QEventLoop(); h = s.queryReady.connect(lambda *_: loop.quit())
    QTimer.singleShot(240000, loop.quit); kick(); loop.exec(); s.queryReady.disconnect(h); pump()
def idle(limit=300):
    t0 = time.time()
    while time.time() - t0 < limit:
        app.processEvents()
        if not c._queue and c._current is None and not c._busy and c._mask_thread is None:
            pump(); return
        time.sleep(0.02)
    raise SystemExit("never idle")

wait(lambda: c.open_recent(str(BUILD))); idle()
assert not bs.btn_datastore.isHidden() and not bs.btn_info.isHidden()
bs.show_datastore_page(); w.tabbar.setCurrentIndex(0); pump()
assert bs.main_stack.currentIndex() == DATASTORE and not bs.btn_close.isHidden()

# foldable groups: a click on the title folds and unfolds
grp = f.grp_columns
assert grp.is_expanded() and grp.title().startswith("▾")
def click(widget, y):
    for kind in (QMouseEvent.Type.MouseButtonPress,):
        ev = QMouseEvent(kind, QPointF(20, y), QPointF(20, y), Qt.MouseButton.LeftButton,
                         Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        widget.mousePressEvent(ev)
click(grp, 4); pump()
assert not grp.is_expanded() and grp.body.isHidden() and grp.title().startswith("▸")
click(grp, 4); pump(); assert grp.is_expanded() and not grp.body.isHidden()
click(grp, grp.height() - 5); pump(); assert grp.is_expanded(), "a click below the title doesn't fold"
print("groups fold from their title")

# layers: thickness first, All layers (From / To greyed), Available
assert f.chk_all_layers.isChecked() and not f.layer_min.isEnabled() and not f.layer_max.isEnabled()
assert f.lbl_available.text() == "Available: 1 - 10 (10 layers)", f.lbl_available.text()
assert f.scope() == (1, 10)
f.chk_all_layers.setChecked(False); f.layer_min.setValue(3); f.layer_max.setValue(6)
assert f.layer_min.isEnabled() and f.scope() == (3, 6)
f.chk_all_layers.setChecked(True); assert f.scope() == (1, 10)
print("layers: All layers, else From / To")

# columns: All / None (required stay) / Default / Clear renames
f.select_columns("all"); assert all(r.included() for r in f._col_rows)
f.select_columns("none"); assert all(r.included() == r.locked for r in f._col_rows)
f.select_columns("default")
assert "Duration" in f.columns() and "Demand focus" not in f.columns()
assert f.renames_map()["Demand X"] == "X"
f.clear_renames(); assert f.renames_map() == {}
f.select_columns("default")
print("columns: All, None, Default, Clear renames")

# Browse...: a chosen STL goes into config.toml and onto the page
stl = next(BUILD.glob("*.stl"))
copy = BUILD / "sub_dir"; copy.mkdir(exist_ok=True)
moved = copy / stl.name; moved.write_bytes(stl.read_bytes())
QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (str(moved), ""))
f.browse_buttons["STL"].click(); pump()
assert f"stl = \"sub_dir/{stl.name}\"" in toml.read_text(encoding="utf-8")
assert f.lbl_stl.text() == str(moved) and c.current_config()["STL"] == moved
print("Browse...: the STL is kept in config.toml")

# processing: Direct's max distance, DBSCAN's chunks, the Part filter
f.cmb_parts.setCurrentText("Direct"); pump()
assert f.direct_detail.isVisible() and f.spin_max_distance.text() == "No limit"
f.spin_max_distance.setValue(25)
assert f.recipe()["max_distance"] == 25
f.cmb_parts.setCurrentText("DBSCAN"); pump()
assert f.dbscan_detail.isVisible() and f.spin_overlap.text() == "Auto"
f.spin_layers_per_chunk.setValue(20); f.spin_overlap.setValue(4)
assert f.recipe()["dbscan"]["layers_per_chunk"] == 20 and f.recipe()["dbscan"]["overlap_layers"] == 4
f.cmb_parts.setCurrentText("Direct"); pump()
assert not f.part_filter.is_expanded() and f.parts_list.count() == 0, "closed, listed on opening"
f.part_filter.button.click(); pump()
names = [f.parts_list.item(i).text() for i in range(f.parts_list.count())]
assert len(names) == 20 and names[0] == "Part(1)", names
f.btn_parts_none.click(); assert f.excluded_parts() == sorted(names)
f.btn_parts_all.click(); assert f.excluded_parts() == []
out = names[:3]
for i in range(3):
    f.parts_list.item(i).setCheckState(Qt.CheckState.Unchecked)
assert f.excluded_parts() == sorted(out) and f.lbl_parts_count.text() == "17 of 20 parts kept"
assert f.recipe()["excluded_parts"] == sorted(out)
print("parts: max distance, DBSCAN chunks, a Part filter of the parts CSV's parts")

# correction: Output, then Override column / New column / name
f.chk_correction.setChecked(True)
assert f.txt_corr_name.placeholderText() == "name…" and f.txt_corr_name.isEnabled()
f.rb_corr_override.setChecked(True); assert not f.txt_corr_name.isEnabled()
f.rb_corr_new.setChecked(True); f.chk_correction.setChecked(False)

# build: the filtered parts are gone from the data, and the choices are kept
f.chk_mask.setChecked(False)   # the test build's STL doesn't reach its first layers
wait(w._on_build_requested); idle()
df = c._base_df
assert df is not None
shaped = c._shape(df)
assert "part_id" in shaped.columns
assert not shaped.filter(pl.col("part_id").is_in(out)).height, "filtered parts are dropped"
assert shaped.filter(pl.col("part_id").is_in(names[3:])).height
saved = uistate.load_state(c.session.store.cache_dir)["parts"]
assert saved == {"max_distance": 25, "excluded": sorted(out)}, saved
assert c.current_config()["MAX_DISTANCE_MM"] == 25
print("build: the Part filter drops its parts; max distance and filter kept")

# reopen: restored on the setup page
wait(lambda: c.open_recent(str(BUILD))); idle()
assert f.excluded_parts() == sorted(out) and f.spin_max_distance.value() == 25
assert not c._shape(c._base_df).filter(pl.col("part_id").is_in(out)).height
print("reopen: the Part filter and max distance come back")

# Info: the build's properties
bs.btn_info.click(); pump()
assert bs.main_stack.currentIndex() == INFO and bs.info_title.text() == BUILD.name
title, sections, folder = c.build_info()
info = {k: v for _, rows in sections for k, v in rows}
assert info["Type"] == "Single build" and info["Built"] == "10 of 10 layers"
assert info["Layers"] == "1 - 10 (10 layers)" and info["Part assignment"].startswith("Direct (max distance 25 mm)")
assert "3 parts filtered out" in info["Part assignment"] and info["STL"] == str(moved)
assert folder == str(BUILD) and not bs.info_reveal.isHidden()
print("Info:", {k: info[k] for k in ("Type", "Built", "Size on disk", "Part assignment")})

# -- Recent: columns, and a library plot as a recent file ----------------------
plot = Path(_harness.ROOT) / "Meltpool by layer.ampmplot"; plot.write_bytes(b"x")
assert kind_of(plot) == "plot" and kind_of(BUILD) == "build"
RecentStore().record(plot, has_cache=True, name="Meltpool by layer")
bs.refresh_recents(); pump()
rows = []
for i in range(bs.recent.count()):
    item = bs.recent.item(i)
    labels = [l.text() for l in bs.recent.itemWidget(item).findChildren(type(bs.info_title))]
    rows.append(labels)
assert rows[0][:3] == ["Meltpool by layer", "Library plot", ""], rows
assert rows[1][:3] == [BUILD.name, "Single build", "ready"], rows
x = [bs.recent.itemWidget(bs.recent.item(i)).findChildren(type(bs.info_title))[1].geometry().x()
     for i in range(2)]
assert x[0] == x[1], "the Type column lines up"
opened = []
bs.libraryOpenRequested.disconnect(); bs.libraryOpenRequested.connect(opened.append)
bs._on_recent_activated(bs.recent.item(0))
assert opened == [str(plot.resolve())]
assert RecentStore().most_recent().path == str(BUILD.resolve()), "start folders come from builds"
print("Recent: type / status / opened in columns; a library plot reopens from it")
assert not told, told
w.close()
print("ALL OK")
