"""Parts CSV sections with duplicated part names: one row per placed copy, keyed Name#<instance>, each with its own values; end to end on the grid.

Args: ORIGINAL_CSV DUPLICATED_BUILD [CSV ...] (the runner makes the duplicated build)."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import os, sys, types
import polars as pl
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from ampm_viewer.shell.controller import AppController
from ampm_viewer.shell.window import MainWindow
from ohpal.ampm.parts import QuantAMParts
ORIG, BUILD = sys.argv[1], sys.argv[2]

def sections(csv):
    stub = types.SimpleNamespace(_parts_csvs=lambda: [("", csv)],
                                 _csv_sections=AppController._csv_sections)
    return dict(AppController.parts_csv_sections(stub))

# 1. builds without duplicate names: keys are the bare names, exactly as before
for csv in sys.argv[3:]:
    qp = QuantAMParts.from_path(csv); new = sections(csv)
    assert "Parent Parts" not in new, "the CSV's own index isn't offered"
    for name, body in new.items():
        df = qp[name]
        if name != "Parent Parts":
            df = df.filter(df["Sr. No."].cast(pl.Utf8).str.ends_with(".1"))
        assert body["part_id"].to_list() == df["Source Index"].to_list(), name
        assert body.drop("part_id").equals(df.drop(["Sr. No.", "Source Index"])), name
    print("unchanged for", os.path.basename(csv), f"({len(new)} sections)")

# 2. duplicated names: one row per copy, keyed Name#<instance>, each with ITS OWN values
dup_csv = next(os.path.join(BUILD, f) for f in os.listdir(BUILD) if f.lower().endswith(".csv"))
orig, dup = sections(ORIG), sections(dup_csv)
parent_ids = QuantAMParts.from_path(dup_csv).parent_parts()["part_id"].to_list()
assert {"Part(5)#5", "Part(5)#6", "Part(5)#7", "Part(5)#8"} <= set(parent_ids), parent_ids
for name, body in dup.items():
    ids = body["part_id"].to_list()
    assert ids == parent_ids, (name, ids[:8])
    assert len(set(ids)) == len(ids), f"{name}: duplicate keys"
    # instance 6 of Part(5) must carry what was Part(6)'s row, etc.
    o = orig[name]
    for inst, was in ((5, "Part(5)"), (6, "Part(6)"), (7, "Part(7)"), (8, "Part(8)")):
        a = body.filter(pl.col("part_id") == f"Part(5)#{inst}").drop("part_id")
        b = o.filter(pl.col("part_id") == was).drop("part_id")
        assert a.equals(b), (name, inst)
print("duplicate names → per-instance keys with per-instance values:", len(dup), "sections")

# 3. end to end on the build: every part row on the grid gets a value
w = MainWindow(); w.show()
loop = QEventLoop(); w.session.queryReady.connect(lambda *_: loop.quit()); QTimer.singleShot(120000, loop.quit)
w.controller.open_recent(BUILD); loop.exec()
for _ in range(20): app.processEvents()
grid_ids = set(w.session.result.df["part_id"].drop_nulls().unique().to_list()) - {"noise"}
print("grid part ids (sample):", sorted(x for x in grid_ids if "#" in x))
assert any("#" in x for x in grid_ids), "test build should have suffixed part ids on the grid"
# The column that tells the parts apart best (most distinct values), so each
# copy's own value is really checked.
sec, body, col = max(((n, b, c) for n, b in w.controller.parts_csv_sections()
                      for c in b.columns if c != "part_id"),
                     key=lambda t: t[1][t[2]].n_unique())
print("checking", sec, "/", col, body[col].n_unique(), "distinct values")
out = w._run("parts_csv_import", items=[[sec, col]]); assert out.ok, out
df = w.session.result.df
parts = df.filter(pl.col("part_id").is_not_null() & (pl.col("part_id") != "noise"))
missing = parts.filter(pl.col(col).is_null())["part_id"].unique().to_list()
assert not missing, f"parts with no imported value: {missing}"
want = dict(zip(body["part_id"].to_list(), body[col].to_list()))
got = parts.group_by("part_id").agg(pl.col(col).n_unique().alias("n"), pl.col(col).first().alias("v"))
def same(a, b):
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return str(a) == str(b)
for pid, n, v in got.iter_rows():
    assert n == 1 and same(v, want[pid]), (pid, v, want[pid])
print(f"end to end: '{col}' matched all {got.height} parts on the grid, each with its own value")
print("ALL PARTS-CSV FIX CHECKS PASS")
try: w.controller.shutdown()
except RuntimeError: pass
