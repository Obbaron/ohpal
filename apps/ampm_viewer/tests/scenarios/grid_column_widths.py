"""Grid columns keep their width by name through column changes; a column
shown in the Show / hide menu is never left with no width (removing a column
used to hand a hidden column's empty slot to a shown one), and a layout
saved like that is mended when it's restored."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import random
from PyQt6.QtWidgets import QApplication
app = QApplication([])
import polars as pl
from ampm_viewer.shell.data_tab import DataTab

def frame(cols):
    return pl.DataFrame({c: [1.0, 2.0] for c in cols})

def widths(dt):
    h = dt.table.horizontalHeader()
    return {n: h.sectionSize(i) for i, n in enumerate(dt.model.columns)
            if not h.isSectionHidden(i)}

def no_empty(dt, where):
    h = dt.table.horizontalHeader()
    empty = [n for i, n in enumerate(dt.model.columns)
             if not h.isSectionHidden(i) and h.sectionSize(i) < 12]
    assert not empty, f"{where}: shown but no width: {empty}"

dt = DataTab(); dt.resize(1200, 500); dt.show()
cols = ["Duration", "Plasma", "Meltpool", "X", "Y", "Z", "part_id", "Hatches Power"]
dt.set_persisted_state(None); dt.set_dataframe(frame(cols)); app.processEvents()
h = dt.table.horizontalHeader()

# 1. what the user saw: Y and Z had been hidden, a column before them was
# removed (a macro), then they were shown again
dt.set_column_visible("Y", False); dt.set_column_visible("Z", False)
cols.remove("Plasma"); dt.set_dataframe(frame(cols)); app.processEvents()
dt.set_column_visible("Y", True); dt.set_column_visible("Z", True)
no_empty(dt, "show after a removal")
assert {"Y", "Z"} <= set(widths(dt))
print("hidden, column removed, shown again: Y and Z have their width")

# 2. widths go with the column, not its slot
h.resizeSection(dt.model.columns.index("Meltpool"), 177)
h.resizeSection(dt.model.columns.index("X"), 66)
before = widths(dt)
cols.remove("Duration"); dt.set_dataframe(frame(cols)); app.processEvents()
after = widths(dt)
assert after["Meltpool"] == 177 and after["X"] == 66, after
assert all(after[n] == before[n] for n in after if n in before), (before, after)
cols.insert(1, "Output power"); dt.set_dataframe(frame(cols)); app.processEvents()
assert widths(dt)["Meltpool"] == 177 and widths(dt)["X"] == 66
print("widths kept by name through a removal and an insertion")

# 3. a layout saved with a shown column at no width is mended on restore
i = dt.model.columns.index("Y")
dt._applying = True; h.resizeSection(i, 0); dt._applying = False
assert h.sectionSize(i) == 0
blob = dt.current_state(); c, o, hid = dt.layout_names()
again = DataTab(); again.resize(1200, 500); again.show()
again.set_persisted_state(blob, c, o, hid); again.set_dataframe(frame(cols))
app.processEvents()
no_empty(again, "restored")
print("a saved layout with an empty column is mended on restore")

# 4. any mix of show / hide / add / remove / undo / reopen leaves none empty
rng = random.Random(7)
extra = ["mp mean", "mp std", "mp cov", "Hatches Speed", "Border Power"]
for step in range(300):
    mc = dt.model.columns
    op = rng.choice(["hide", "show", "add", "remove", "layer", "undo", "reopen"])
    if op == "hide":
        dt.set_column_visible(rng.choice(mc), False)
    elif op == "show":
        dt.set_column_visible(rng.choice(mc), True)
    elif op == "add" and [e for e in extra if e not in cols]:
        cols.insert(rng.randrange(len(cols) + 1),
                    rng.choice([e for e in extra if e not in cols]))
        dt.set_dataframe(frame(cols))
    elif op == "remove" and len(cols) > 4:
        cols.remove(rng.choice(cols)); dt.set_dataframe(frame(cols))
    elif op == "layer":
        dt.set_dataframe(frame(cols))
    elif op == "undo":
        dt.apply_hidden(set(rng.sample(mc, rng.randint(0, min(3, len(mc))))))
    elif op == "reopen":
        blob = dt.current_state(); c, o, hid = dt.layout_names()
        dt.set_persisted_state(blob, c, o, hid); dt.set_dataframe(frame(cols))
    app.processEvents()
    no_empty(dt, f"step {step} ({op})")
print("300 random layout changes: no shown column without a width")
print("ALL OK")
