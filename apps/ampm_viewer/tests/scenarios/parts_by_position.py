"""Parts CSV and samples-template imports land on the right parts whichever
part assignment names them, by matching parts on position, not name.

QuantAM names parts its own way (on JR343, ``Part(2)`` ... ``Part(16)``: its
``Part(1)`` was deleted) and the .dhxml its way (``1`` ... ``15``). By name, a
DHXML-assigned build got each part's neighbour's CSV values; a
Direct-assigned one its neighbour's template values. Here every imported
value is checked against the CSV / template row at that part's place, under
the build's assignment (run it on a DHXML- and a Direct-assigned copy). On
a build whose names agree, JR299, this is the same as matching by name."""
import _harness  # noqa: F401  (first: temp settings and folders, see _harness.py)
import os, sys, time
from pathlib import Path
BUILD = sys.argv[1]
# This copy's config names its .dhxml (JR299's doesn't, though it has one).
_cfg = Path(BUILD) / "config.toml"
_dh = next(Path(BUILD).glob("*.dhxml"), None)
if _dh is not None and "dhxml" not in _cfg.read_text():
    _cfg.write_text(_cfg.read_text().replace("[paths]\n", f"[paths]\ndhxml = '{_dh.name}'\n", 1))
import numpy as np
import polars as pl
from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from openpyxl import load_workbook
from ohpal.ampm.parts import BuildStartedDHXML, QuantAMParts
from ohpal.ampm.template import make_template
from ampm_viewer.shell import controller as cmod, excel_dialog
from ampm_viewer.shell.derive import norm_key
from ampm_viewer.shell.window import MainWindow
cmod._tell = lambda *a, **k: None
w = MainWindow(); w.resize(1200, 760); w.show(); c, s = w.controller, w.session
def drain():
    t0 = time.time()
    while time.time() - t0 < 300:
        app.processEvents()
        if not c._queue and c._current is None and not c._busy:
            for _ in range(20): app.processEvents(); time.sleep(0.002)
            if not c._queue and c._current is None and not c._busy: return
        time.sleep(0.01)
loop = QEventLoop(); s.queryReady.connect(lambda *_: loop.quit())
QTimer.singleShot(240000, loop.quit); c.open_recent(BUILD); loop.exec(); drain()
cfg = c._config
assert cfg.get("DHXML") and cfg.get("PARTS_CSV"), "needs a build with a .dhxml and a parts CSV"

# Independently: the CSV's Hatches Power for the part at each place, and each
# assigned part's place (its box from the dhxml; its centre from the CSV).
qp = QuantAMParts.from_path(cfg["PARTS_CSV"])
csv_parts = qp.parent_parts()
power = dict(zip(qp.volume_parameters()["part_id"], qp.volume_parameters()["Hatches Power"]))
dh = BuildStartedDHXML.from_dhxml(cfg["DHXML"]).parts_table()
def csv_power_at(x, y):
    d = np.hypot(csv_parts["x_center"].to_numpy() - x, csv_parts["y_center"].to_numpy() - y)
    return float(power[csv_parts["part_id"][int(np.argmin(d))]])

# The samples template, with a made-up density per part from its own centre
# (so the right value for any part is known from its place alone).
root = Path(BUILD)
xlsx = make_template(Path(cfg["DHXML"]), _harness.ROOT / "samples.xlsx",
                     quant=Path(cfg["PARTS_CSV"]))
wb = load_workbook(xlsx); ws = wb.worksheets[0]
heads = [cc.value for cc in ws[1]]
ix = {h: heads.index(h) + 1 for h in ("x_min", "x_max", "y_min", "y_max")}
ws.cell(row=1, column=len(heads) + 1, value="Density")
def density_at(x, y):
    return round(4.0 + x / 1000 + y / 10000, 6)
for r in range(2, ws.max_row + 1):
    cx = (ws.cell(row=r, column=ix["x_min"]).value + ws.cell(row=r, column=ix["x_max"]).value) / 2
    cy = (ws.cell(row=r, column=ix["y_min"]).value + ws.cell(row=r, column=ix["y_max"]).value) / 2
    ws.cell(row=r, column=len(heads) + 1, value=density_at(cx, cy))
wb.save(xlsx)

def part_places(method):
    """Each assigned part id (normalised) -> its centre, as the method sees it."""
    table = dh if method == "dhxml" else csv_parts
    return {norm_key(p): (x, y) for p, x, y in
            zip(table["part_id"], table["x_center"], table["y_center"])}

results = {}
for method in [str(cfg.get("METHOD") or "").lower()]:  # as the build is set up
    assert method in ("dhxml", "direct"), method
    pid = c.part_id_display()
    n0 = len(s.derivations)
    # Parts CSV: Scan Volume ▸ Hatches Power
    sections = dict(c.parts_csv_sections())
    assert w._run("parts_csv_import", items=[["Scan Volume", "Hatches Power"]]), method
    drain()
    status = w._log.text()
    hp = s.derivations[-1]["name"]
    # Samples template: Density, through the dialog's own alignment
    align = c.excel_key_alignment(xlsx, ws.title, "part_id")
    mapping, dtype, _n = excel_dialog.parse_mapping(xlsx, ws.title, "part_id", "Density", align=align)
    assert w._run("excel_import", name=f"Density {method}", key=pid, mapping=mapping, dtype=dtype)
    drain()
    places = part_places(method)
    df = s.result.df.select(pid, hp, f"Density {method}").unique(subset=[pid]).drop_nulls(pid)
    df = df.filter(pl.col(pid).cast(pl.Utf8) != "noise")
    checked = 0
    for p, got_power, got_density in df.iter_rows():
        x, y = places[norm_key(p)]
        assert got_power == csv_power_at(x, y), (method, p, got_power, csv_power_at(x, y))
        # (the CSV's centre and the dhxml box's differ by microns; parts by >10 mm)
        assert abs(got_density - density_at(x, y)) < 1e-4, (method, p, got_density, density_at(x, y))
        checked += 1
    assert checked >= 1, (method, df)
    results[method] = (checked, status)
    print(f"{method}: {checked} parts on this layer, every Hatches Power and Density at its own place | {status}")

for method, (n, status) in results.items():
    assert "parts by position" in status or method == "direct", (method, status)
    assert "are at no part" not in status, status
print("PARTS BY POSITION CHECKS PASS")
c.shutdown()
os._exit(0)
