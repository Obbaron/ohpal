"""Tests for ohpal.ampm.batch and make_template_from_quant."""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

from ohpal.ampm.batch import generate_build_templates
from ohpal.ampm.template import make_template_from_quant
from ohpal.samples.io import read_table

U = Path("/mnt/user-data/uploads")
REAL = {
    "JR295": U / "JR295_parts.csv",
    "JR299": U / "JR299_sterling_parts.csv",
    "JR324": U / "JR324_parts.csv",
    "Untitled": U / "Untitled.csv",
}
DHXML = U / "BuildStarted_2025_12_2_13_37_55.dhxml"
_HAVE_REAL = all(p.exists() for p in REAL.values()) and DHXML.exists()
skip_real = pytest.mark.skipif(not _HAVE_REAL, reason="real build data not present")


# ---- make_template_from_quant (synthetic) ---------------------------------

def _quant_csv(tmp_path: Path, part_ids, positions) -> Path:
    """Write a minimal QuantAM export with Parent Parts + Scan Volume tabs."""
    lines = ["#,Renishaw,Material,Development", ",Version,0.6.1", ""]
    lines += ["#,Tab - -1,Parent Parts",
              '#,"Sr. No.","Source Index","Layer Thickness","X Position","Y Position","Layers Count","Part Type",',
              'ID.,"[T0C1]","[T0C2]","[T-1C1]","[T-1C2]","[T-1C3]","[T-1C4]","[T-1C5]",']
    for i, (pid, (x, y)) in enumerate(zip(part_ids, positions), 1):
        lines.append(f',"{i}","{pid}","0.03","{x}","{y}","333","Geometry Part",')
    lines.append("")
    lines += ["#,Tab - 10,Scan Volume",
              '#,"Sr. No.","Source Index","Hatches Power","Hatches Point Distance","Hatches Exposure Time",',
              'ID.,"[T0C1]","[T0C2]","[T10C5]","[T10C7]","[T10C8]",']
    for i, pid in enumerate(part_ids, 1):
        lines.append(f',"{i}.1","{pid}","200","90","90",')
    lines.append("")
    p = tmp_path / "parts.csv"
    p.write_text("\n".join(lines), encoding="utf-8")
    return p


def test_quant_alone_template(tmp_path):
    csv = _quant_csv(tmp_path, ["Part(1)", "Part(2)"], [(5.0, 5.0), (15.0, 5.0)])
    out = make_template_from_quant(csv, tmp_path / "b.xlsx", build_id="B1")
    back = read_table(out, anchor="part_id")
    assert back["part_id"].to_list() == ["1", "2"]          # Part(N) unwrapped
    assert back["build_id"].to_list() == ["B1", "B1"]
    assert set(back.columns) >= {"build_id", "part_id", "alias", "x", "y"}
    assert "x_min" not in back.columns                       # point, not bounds
    assert back["x"].to_list() == [5.0, 15.0]


def test_quant_alone_keeps_duplicate_suffix(tmp_path):
    csv = _quant_csv(tmp_path, ["Part(1)#1", "Part(1)#2"], [(5.0, 5.0), (6.0, 6.0)])
    out = make_template_from_quant(csv, tmp_path / "b.xlsx", build_id="B1")
    back = read_table(out, anchor="part_id")
    assert back["part_id"].to_list() == ["1#1", "1#2"]


def test_quant_alone_without_params(tmp_path):
    csv = _quant_csv(tmp_path, ["Part(1)"], [(5.0, 5.0)])
    out = make_template_from_quant(csv, tmp_path / "b.xlsx", build_id="B1", include_params=False)
    back = read_table(out, anchor="part_id")
    assert "Hatch Speed" not in back.columns and "speed" not in back.columns


# ---- batch discovery (synthetic) ------------------------------------------

def _dhxml(path: Path, boxes):
    parts = [{"name": n, "boundingBox": bb} for n, bb in boxes]
    path.write_text(json.dumps({"version1": {"build": {"mttFileName": "JobA_x.mtt",
                    "parts": parts}}}), encoding="utf-8")


def test_batch_pairs_and_falls_back(tmp_path):
    data, out = tmp_path / "data", tmp_path / "out"
    data.mkdir()
    # build A: dhxml with two boxes + a CSV whose positions are inside them
    _dhxml(data / "A.dhxml", [("1", "0,0,0,10,10,10"), ("2", "11,0,0,21,10,10")])
    _quant_csv(data, ["Part(1)", "Part(2)"], [(5, 5), (15, 5)]).rename(data / "A_parts.csv")
    # build B: a CSV only, positions far away (no dhxml)
    bdir = data / "b"; bdir.mkdir()
    _quant_csv(bdir, ["Part(1)"], [(500, 500)]).rename(bdir / "B_parts.csv")

    results = generate_build_templates(data, out)
    by_source = {r.source for r in results}
    assert "dhxml+quant" in by_source           # A paired
    assert "quant" in by_source                 # B fell back
    assert all(r.out_path and r.out_path.exists() for r in results)
    assert len(results) == 2


def test_batch_no_false_pair_across_builds(tmp_path):
    # two separate builds; each CSV must map to its own dhxml, not the other.
    data, out = tmp_path / "data", tmp_path / "out"
    data.mkdir()
    _dhxml(data / "A.dhxml", [("1", "0,0,0,10,10,10")])
    _quant_csv(data, ["Part(1)"], [(5, 5)]).rename(data / "A_parts.csv")
    results = generate_build_templates(data, out)
    assert len(results) == 1 and results[0].source == "dhxml+quant"


# ---- real data ------------------------------------------------------------

@skip_real
def test_batch_real_corpus(tmp_path):
    data, out = tmp_path / "data", tmp_path / "out"
    (data / "jr299").mkdir(parents=True)
    import shutil
    shutil.copy(REAL["JR299"], data / "jr299" / "JR299_sterling_parts.csv")
    shutil.copy(DHXML, data / "jr299" / "BuildStarted.dhxml")
    for k in ("JR295", "JR324", "Untitled"):
        shutil.copy(REAL[k], data / f"{k}.csv")

    results = generate_build_templates(data, out, rename={"Hatch Speed": "speed", "Hatches Power": "power"})
    srcs = {r.build_id: r.source for r in results}
    assert srcs.get("JR299_OHP_Ti-Sterling") == "dhxml+quant"   # paired
    assert srcs.get("JR324") == "quant"                          # no false-pair
    assert len(results) == 4
    assert all(r.out_path.exists() for r in results)
