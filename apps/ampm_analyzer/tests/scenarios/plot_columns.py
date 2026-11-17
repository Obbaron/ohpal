"""A plot holds only what it needs: its query brings the source columns it
depends on (what it draws and filters on, through the calculations that make
them), and the frame it draws keeps only its own columns and its filter's
rows. Column changes still reach it (re-shaped, or queried again when it now
needs a column it didn't bring)."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import sys, time
BUILD = sys.argv[1]
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from ampm_analyzer.shell import controller as cmod, plotneeds
from ampm_analyzer.shell.plotspec import PlotSpec
from ampm_analyzer.shell.window import MainWindow

cmod._tell = lambda *a, **k: None
w = MainWindow(); w.resize(1200, 760); w.show(); c, s = w.controller, w.session
def drain(limit=300):
    t0 = time.time()
    while time.time() - t0 < limit:
        app.processEvents()
        if not c._queue and c._current is None and not c._busy:
            for _ in range(30): app.processEvents(); time.sleep(0.003)
            if not c._queue and c._current is None: return
        time.sleep(0.01)
loop = QEventLoop(); h = s.queryReady.connect(lambda *_: loop.quit())
QTimer.singleShot(240000, loop.quit); c.open_recent(BUILD); loop.exec(); drain()
ALL = ("all", None, None)
cols = list(s.result.df.columns); X, Y = "Demand X", "Demand Y"
MP = next(n for n in cols if "elt" in n and "ool" in n)
LV = next(n for n in cols if n.startswith("LaserVIEW"))
n_source = len(s.store.columns)
assert n_source > 10, n_source

# --- the pieces --------------------------------------------------------------------------
spec = PlotSpec(kind="2D Scatter", x=X, y=Y, color="twice")
ders = [{"name": "base", "expr": f"[{MP}] + 1"}, {"name": "twice", "expr": "[base] * 2", "group": "part_id"},
        {"name": "band", "kind": "label", "rules": [{"cond": f"[{LV}] > 0", "label": "on"}]},
        {"name": "gas", "kind": "join", "key": "layer", "map": {"1": 1.0}}]
assert plotneeds.needed_columns(spec, derivations=ders) == {X, Y, "twice", "base", MP, "part_id", "layer"}
assert plotneeds.needed_columns(spec, derivations=ders, filters=["[band] == 'on'"]) >= {"band", LV}
assert plotneeds.source_columns(spec, derivations=ders, renames={MP: "Pool"},
                                filters=[]) == sorted({X, Y, MP, "part_id", "layer"}), "calculations aren't sources"
sp2 = PlotSpec(kind="2D Scatter", x=X, y=Y, color="Pool")
assert MP in plotneeds.source_columns(sp2, renames={MP: "Pool"}), "a renamed column is queried by its own name"
assert plotneeds.source_columns(PlotSpec(kind="Histogram", x=MP, y="count"), available=[MP, "layer"]) == sorted([MP, "layer"])
print("dependencies: drawn, filtered on, through calculations; renamed back to their source names")

# --- a plot's frames ------------------------------------------------------------------------
THR = float(s.result.df[LV].median())          # a filter on a column the plot doesn't draw
w._run("filter_add", condition=f"[{LV}] > {THR}"); drain()
t = w._open_plot(PlotSpec(kind="2D Scatter", x=X, y=Y, color=MP), ALL); drain()
w._remove_filter_at(0); drain()
assert t.row_filter == [f"[{LV}] > {THR}"]
assert set(t._df.columns) == {X, Y, MP, "part_id", "layer"}, t._df.columns
assert LV in t.raw.columns and len(t.raw.columns) < n_source, t.raw.columns   # its filter's column is queried
assert 0 < (t.raw[LV] > THR).sum() < t.raw.height and t._df.height == (t.raw[LV] > THR).sum(), \
    "it draws (and holds) only its filter's rows"
every = lambda: s.store.query(layers=(min(s.store.layers), max(s.store.layers)),
                              sample_to=cmod._PLOT_SAMPLE_ROWS)   # every column
full = c.shape_filtered(every(), t.row_filter)
assert full.height == t._df.height and abs(float(full[MP].sum()) - float(t._df[MP].sum())) < 1e-6 * abs(float(full[MP].sum())), \
    "the same points as from every column"
print(f"scatter: queried {len(t.raw.columns)} of {n_source} columns; draws {t._df.width} columns, {t._df.height:,} rows")

# a calculated colour: its inputs come along, the grouped calculation sees every row
w._run("derive", name="dev", expr=f"[{MP}] - mean([{MP}]) by [part_id]"); drain()
td = w._open_plot(PlotSpec(kind="2D Scatter", x=X, y=Y, color="dev"), ALL); drain()
assert MP in td.raw.columns and "dev" in td._df.columns and MP not in td._df.columns
assert abs(float(td._df["dev"].mean())) < 1e-3 * float(full[MP].abs().mean()), "deviation from the part means of all rows"
# redefined from a column the plot didn't bring: it queries again
before = td.raw
w._run("derive", name="dev", expr=f"[{LV}] * 1", overwrite=True); drain()
assert td.raw is not before and LV in td.raw.columns
want = float(c.shape_filtered(every(), [])[LV].sum())
assert abs(float(td._df["dev"].sum()) - want) <= 1e-6 * max(1.0, abs(want)), "drawn from its new input"
# a rename re-shapes without a query (its source name is unchanged)
raw_before = td.raw
w._run("rename", old=X, new="Xpos"); drain()
assert td.spec.x == "Xpos" and "Xpos" in td._df.columns and td.raw is raw_before
print("calculated columns: inputs queried; a redefinition queries again, a rename re-shapes")

# a narrowed frame that misses something falls back to every column
real = c.plot_sources
c.plot_sources = lambda spec, row_filter: [MP, "layer"]          # forgets the axes
tf = w._open_plot(PlotSpec(kind="2D Scatter", x="Xpos", y=Y, color=MP), ALL)
drain(); c.plot_sources = real
assert tf._all_columns and "Xpos" in tf._df.columns and len(tf.raw.columns) >= n_source - 1
c.shutdown()
print("PLOT COLUMN CHECKS PASS")
