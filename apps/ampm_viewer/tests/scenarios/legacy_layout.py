"""A build exported by the older DataHUB (seven columns: 'Start time / us',
'x position / mm', 'LaserVIEW', ...) opens like any other: its columns are
read under their current names, only the ones it has are offered and loaded
(no blank focus / laser power / median columns), the melt-pool correction
works as on a current build, and the build's info says which layout it is.
A build mixing the two layouts is refused before anything is converted, and
so is a stack whose steps mix them (in the New stacked build dialog, and
when a stack file names such steps).

The older build here is the test build with its packet files rewritten in
the older layout. A second argument, a folder of real older-layout packet
files, is used instead when given (then the parts don't line up, which is
fine: this is about the columns)."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import os, shutil, sys, tempfile, time
from pathlib import Path
BUILD, TMP = Path(sys.argv[1]), Path(tempfile.mkdtemp())
REAL = Path(sys.argv[2]) if len(sys.argv) > 2 else None
import numpy as np
import polars as pl
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from ohpal.ampm.correction import MeltPoolCorrection
from ohpal.ampm.stacked import write_stack
from ampm_viewer.shell import controller as cmod, stackbuild
from ampm_viewer.shell.window import MainWindow, error_line
cmod._tell = lambda *a, **k: None

# The older export: these columns, under these names, in this order.
OLD = {"Start time": "Start time / us", "Duration": "Duration / us",
       "Demand X": "x position / mm", "Demand Y": "y position / mm",
       "LaserVIEW (mean)": "LaserVIEW", "MeltVIEW plasma (mean)": "MeltVIEW Plasma",
       "MeltVIEW melt pool (mean)": "MeltVIEW Melt Pool"}
PACKETS = "[3] Export Packets"

old = TMP / f"{BUILD.name} older"
shutil.copytree(BUILD, old, ignore=shutil.ignore_patterns(".cache", "Packet data*"))
if REAL is not None:
    for f in REAL.iterdir():
        if f.name.startswith("Packet data"):
            shutil.copy(f, old / PACKETS / f.name)
else:
    for f in (BUILD / PACKETS).glob("Packet data*.txt"):
        df = pl.read_csv(f, separator="\t", glob=False)
        df.select(list(OLD)).rename(OLD).write_csv(
            old / PACKETS / f.name, separator="\t", line_terminator="\r\n")
head = (next((old / PACKETS).glob("Packet data*.txt"))).read_text().splitlines()[0]
assert head.split("\t") == list(OLD.values()), head

w = MainWindow(); w.resize(1300, 760); w.show(); c, s = w.controller, w.session
c._confirm = lambda *a, **k: True


def wait(sig, kick, limit=240000):
    got = []
    loop = QEventLoop()
    h = sig.connect(lambda *a: (got.append(a), loop.quit()))
    QTimer.singleShot(limit, loop.quit); kick(); loop.exec(); sig.disconnect(h)
    for _ in range(30): app.processEvents()
    return got[0] if got else None


def drain(limit=300):
    t0 = time.time()
    while time.time() - t0 < limit:
        app.processEvents()
        if not c._queue and c._current is None and not c._busy and c._mask_thread is None:
            for _ in range(40): app.processEvents()
            return
        time.sleep(0.02)
    raise SystemExit("never went idle")


# -- a new build: only its own columns are offered ---------------------------
assert wait(s.setupRequired, lambda: c._load(old, "new")) is not None, w._log.text()
store = s.store
assert store.layout.kind == "legacy", store.layout.kind
have = [*OLD, "layer", "Z"]
assert sorted(c_ for c_ in store.columns if c_ != "part_id") == sorted(have), store.columns
f = w.backstage.ds_form
rows = {r.name: r for r in f._col_rows}
assert sorted(rows) == sorted(have), sorted(rows)
assert not any(n in rows for n in ("Demand focus", "Demand laser power (mean)",
                                   "Laser output power (mean)", "LaserVIEW (median)"))
assert rows["LaserVIEW (mean)"].locked and rows["LaserVIEW (mean)"].included()
assert set(f.columns()) == set(have), f"every column it has is ticked: {f.columns()}"
print("setup: the older layout's 7 columns (+ layer, Z), named as now, all ticked")

# -- built with the melt-pool correction, as on a current build ---------------
assert f.chk_correction.isEnabled(), f.chk_correction.toolTip()
f.chk_correction.setChecked(True)
f.chk_mask.setChecked(False)   # the test build's STL doesn't reach its first layers
assert wait(s.queryReady, w._on_build_requested) is not None, w._log.text()
drain()
shaped = c._shape(c._base_df)
corr = [n for n in shaped.columns if "corrected" in n.lower()]
assert len(corr) == 1, shaped.columns
grid = w._data_tab._columns
assert not any(("focus" in n or "median" in n or "output power" in n.lower()
                or "Demand Power" == n) for n in grid), grid
raw = store.query(columns=list(OLD))
want = MeltPoolCorrection().apply(raw, output_col="__want")
key = ["layer", "Start time"]
both = shaped.select([*key, corr[0]]).join(want.select([*key, "__want"]), on=key)
assert both.height == shaped.height > 0, (both.height, shaped.height)
a, b = both[corr[0]].to_numpy(), both["__want"].to_numpy()
assert np.allclose(a, b, equal_nan=True) and np.isfinite(a).mean() > 0.99, "corrected as on a current build"
print(f"build: {shaped.height:,} rows; '{corr[0]}' = MeltPoolCorrection on LaserVIEW; "
      f"grid {sorted(grid)}")

_, sections, _ = c.build_info()
info = {k: v for _, rows_ in sections for k, v in rows_}
assert info["Packet data"].startswith("DataHUB export, older layout"), info["Packet data"]
assert info["Columns"].startswith(f"{len(have)} of "), info["Columns"]  # (of: + part_id)
print("info:", info["Packet data"])

# -- reopened from its cache -------------------------------------------------
assert wait(s.queryReady, lambda: c.open_recent(str(old))) is not None, w._log.text()
drain()
assert s.store.layout.kind == "legacy" and corr[0] in c._shape(c._base_df).columns
print("reopen: from the cache, correction kept")

# -- a build mixing layouts is refused before anything is converted ----------
layers = sorted(s.store.layers)
src = next((BUILD / PACKETS).glob("Packet data*.txt"))   # the current layout
mixed = old / PACKETS / f"Packet data for layer {layers[-1] + 1}, laser 4.txt"
shutil.copy(src, mixed)
cache = s.store.cache_dir
before = {p.name: p.stat().st_mtime for p in cache.glob("*.parquet")}
assert wait(s.setupRequired, lambda: c._load(old, "new")) is not None   # overwrite
failed = wait(s.loadFailed, w._on_build_requested)
assert failed is not None, "a mixed build should fail"
# The status bar shows the error's own message (it may be shortened to fit).
status = error_line(failed[0])
assert "Load failed: This build mixes DataHUB exports:" in w.log_bus.history()
assert status.startswith("This build mixes DataHUB exports: layer "), status
assert f"layer {layers[-1] + 1} in the current DataHUB layout" in status, status
after = {p.name: p.stat().st_mtime for p in cache.glob("*.parquet")}
assert after == before, "nothing converted (none rewritten, none added)"
drain()
print("mixed build:", status)
mixed.unlink()

# -- stacks: one layout for every step ---------------------------------------
dlg = stackbuild.NewStackDialog(None, start_dir=str(TMP))
assert dlg.add_step(old) is None
err = dlg.add_step(BUILD)
assert err == (f"{BUILD.name} is in the current DataHUB layout but {old.name} is in "
               f"the older DataHUB layout: a stack's steps must all use the same one."), err
assert dlg.list.count() == 1, "the step isn't added"
print("stack dialog:", err)

stack = TMP / "mixed stack"
write_stack(stack, "mixed", [old, BUILD])
failed = wait(s.loadFailed, lambda: c._load(stack, "new"))
assert failed is not None, "a mixed stack should fail"
status = error_line(failed[0])
assert "Load failed: This stack mixes DataHUB exports:" in w.log_bus.history()
assert status.startswith("This stack mixes DataHUB exports: step S1"), status
assert status.endswith("Every step of a stack must use the same layout."), status
print("mixed stack:", status)
c.shutdown()   # waits for background work (the reopened build's mask)
print("OK")
os._exit(0)
