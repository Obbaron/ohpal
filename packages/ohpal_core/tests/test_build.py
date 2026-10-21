"""Tests for ohpal.core.build.

Covers the two responsibilities of the module: parsing the BuildStarted dhxml
into a canonical part table, and the strict point-in-bounding-box resolver.
Synthetic fixtures keep the tests hermetic; add a real dhxml under
tests/data/ and point REAL_DHXML at it for an end-to-end check.
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

from ohpal.core.build import (
    BuildFileError,
    BuildParts,
    PartResolutionError,
    _parse_bounding_box,
    _suffix_duplicate_names,
)


def _write_dhxml(tmp_path: Path, parts: list[dict]) -> Path:
    doc = {"version1": {"build": {"parts": parts}}}
    p = tmp_path / "BuildStarted.dhxml"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


# Two unit squares side by side with a 1mm gap, spanning z 0..10.
GRID = [
    {"name": "A", "boundingBox": "0,0,0,10,10,10"},
    {"name": "B", "boundingBox": "11,0,0,21,10,10"},
]


# ---- parsing --------------------------------------------------------------

def test_parse_bounding_box_normalises_min_max():
    assert _parse_bounding_box("10,10,10,0,0,0") == (0, 0, 0, 10, 10, 10)


def test_parse_bounding_box_rejects_wrong_arity():
    with pytest.raises(ValueError):
        _parse_bounding_box("1,2,3")


def test_from_dhxml_reads_parts(tmp_path):
    b = BuildParts.from_dhxml(_write_dhxml(tmp_path, GRID))
    assert len(b) == 2
    assert b.part_ids == ["A", "B"]
    assert b.part_names == ["A", "B"]


def test_missing_file_raises_buildfileerror(tmp_path):
    with pytest.raises(BuildFileError):
        BuildParts.from_dhxml(tmp_path / "nope.dhxml")


def test_bad_json_raises_buildfileerror(tmp_path):
    p = tmp_path / "bad.dhxml"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(BuildFileError):
        BuildParts.from_dhxml(p)


def test_wrong_layout_raises_buildfileerror(tmp_path):
    p = tmp_path / "wrong.dhxml"
    p.write_text(json.dumps({"something": "else"}), encoding="utf-8")
    with pytest.raises(BuildFileError):
        BuildParts.from_dhxml(p)


# ---- canonical key + dedup ------------------------------------------------

def test_duplicate_names_get_suffixed():
    parts = [{"name": "P", "bbox": (0, 0, 0, 1, 1, 1)},
             {"name": "P", "bbox": (2, 2, 0, 3, 3, 1)},
             {"name": "Q", "bbox": (4, 4, 0, 5, 5, 1)}]
    out = _suffix_duplicate_names(parts)
    assert [p["part_id"] for p in out] == ["P#1", "P#2", "Q"]
    # original names preserved
    assert [p["name"] for p in out] == ["P", "P", "Q"]


def test_parts_table_is_canonical(tmp_path):
    b = BuildParts.from_dhxml(_write_dhxml(tmp_path, GRID))
    pt = b.parts_table()
    assert pt.columns == [
        "part_id", "name",
        "x_min", "y_min", "z_min", "x_max", "y_max", "z_max",
        "x_center", "y_center",
    ]
    assert pt.schema["part_id"] == pl.String
    assert pt.schema["x_center"] == pl.Float64
    # centre of A is (5, 5)
    a = pt.filter(pl.col("part_id") == "A").row(0, named=True)
    assert (a["x_center"], a["y_center"]) == (5.0, 5.0)


# ---- point-in-bbox policy -------------------------------------------------

def test_part_at_inside_returns_part(tmp_path):
    b = BuildParts.from_dhxml(_write_dhxml(tmp_path, GRID))
    assert b.part_at(5, 5) == "A"
    assert b.part_at(15, 5) == "B"


def test_part_at_outside_raises(tmp_path):
    b = BuildParts.from_dhxml(_write_dhxml(tmp_path, GRID))
    with pytest.raises(PartResolutionError):
        b.part_at(50, 50)


def test_part_at_in_gap_raises_without_tol(tmp_path):
    b = BuildParts.from_dhxml(_write_dhxml(tmp_path, GRID))
    with pytest.raises(PartResolutionError):
        b.part_at(10.5, 5)  # in the 1mm gap between A and B


def test_part_at_tolerance_resolves_unique_nearest(tmp_path):
    b = BuildParts.from_dhxml(_write_dhxml(tmp_path, GRID))
    # 0.2mm past A's right edge, far from B -> A wins within tol
    assert b.part_at(10.2, 5, tol=0.5) == "A"


def test_part_at_tolerance_refuses_ambiguous_nearest(tmp_path):
    # Two boxes equidistant from a point in the gap -> refuse even within tol.
    parts = [
        {"name": "L", "boundingBox": "0,0,0,10,10,10"},
        {"name": "R", "boundingBox": "12,0,0,22,10,10"},
    ]
    b = BuildParts.from_dhxml(_write_dhxml(tmp_path, parts))
    with pytest.raises(PartResolutionError):
        b.part_at(11, 5, tol=2.0)  # exactly 1mm from each edge


def test_overlapping_boxes_raise(tmp_path):
    parts = [
        {"name": "X", "boundingBox": "0,0,0,10,10,10"},
        {"name": "Y", "boundingBox": "5,5,0,15,15,10"},  # overlaps X
    ]
    b = BuildParts.from_dhxml(_write_dhxml(tmp_path, parts))
    with pytest.raises(PartResolutionError):
        b.part_at(7, 7)  # inside both


def test_part_ids_at_adds_column(tmp_path):
    b = BuildParts.from_dhxml(_write_dhxml(tmp_path, GRID))
    origins = pl.DataFrame({"cube": ["c1", "c2"], "x": [5.0, 15.0], "y": [5.0, 5.0]})
    out = b.part_ids_at(origins)
    assert out["part_id"].to_list() == ["A", "B"]
    assert out.schema["part_id"] == pl.String
    # row order / other columns preserved
    assert out["cube"].to_list() == ["c1", "c2"]


def test_part_ids_at_hard_fails_on_unresolvable(tmp_path):
    b = BuildParts.from_dhxml(_write_dhxml(tmp_path, GRID))
    origins = pl.DataFrame({"x": [5.0, 999.0], "y": [5.0, 999.0]})
    with pytest.raises(PartResolutionError):
        b.part_ids_at(origins)


# ---- build identity (mtt / name) ------------------------------------------

def _write_build(tmp_path, *, parts, **build_fields):
    doc = {"version1": {"build": {"parts": parts, **build_fields}}}
    p = tmp_path / "BuildStarted.dhxml"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def test_build_id_from_mtt_stem(tmp_path):
    b = BuildParts.from_dhxml(_write_build(
        tmp_path, parts=GRID, mttFileName="JobX_OHP_Foo.mtt", name=""))
    assert b.mtt_filename == "JobX_OHP_Foo.mtt"
    assert b.build_id == "JobX_OHP_Foo"          # stem, extension stripped


def test_build_id_falls_back_to_name(tmp_path):
    b = BuildParts.from_dhxml(_write_build(tmp_path, parts=GRID, name="MyBuild"))
    assert b.mtt_filename is None
    assert b.build_id == "MyBuild"


def test_build_id_none_when_absent(tmp_path):
    b = BuildParts.from_dhxml(_write_build(tmp_path, parts=GRID, name=""))
    assert b.build_id is None


REAL_DHXML = Path("/mnt/user-data/uploads/BuildStarted_2025_12_2_13_37_55.dhxml")


@pytest.mark.skipif(not REAL_DHXML.exists(), reason="build file not present")
def test_real_build_id():
    b = BuildParts.from_dhxml(REAL_DHXML)
    assert b.mtt_filename == "JR299_OHP_Ti-Sterling.mtt"
    assert b.build_id == "JR299_OHP_Ti-Sterling"
