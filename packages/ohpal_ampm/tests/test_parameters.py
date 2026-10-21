"""Tests for ohpal.ampm.parameters.part_parameters (position-mapped params).

Synthetic fixtures exercise the mapping/policy logic hermetically. Real-data
checks against an uploaded QuantAM CSV + its dhxml are skip-guarded, matching
the convention in the other packages.
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

from ohpal.core.build import BuildParts
from ohpal.ampm.parameters import (
    DEFAULT_PARAMETER_COLUMNS,
    ParameterMappingError,
    part_parameters,
)

# Optional real pair (same build): QuantAM CSV + dhxml. Point these at local
# copies to run the end-to-end checks.
REAL_CSV = Path("/mnt/user-data/uploads/JR299_sterling_parts.csv")
REAL_DHXML = Path("/mnt/user-data/uploads/BuildStarted_2025_12_2_13_37_55.dhxml")


def _build(tmp_path: Path, boxes) -> BuildParts:
    parts = [{"name": n, "boundingBox": bb} for n, bb in boxes]
    p = tmp_path / "BuildStarted.dhxml"
    p.write_text(json.dumps({"version1": {"build": {"parts": parts}}}), encoding="utf-8")
    return BuildParts.from_dhxml(p)


class _FakeQuant:
    """Minimal stand-in for QuantAMParts: supplies volume_parameters_with_speed."""

    def __init__(self, df: pl.DataFrame):
        self._df = df

    def volume_parameters_with_speed(self, *, variant: str = "1") -> pl.DataFrame:
        return self._df


# Two unit boxes with a gap, spanning z 0..10.
GRID = [("1", "0,0,0,10,10,10"), ("2", "11,0,0,21,10,10")]


def _params(rows):
    return _FakeQuant(pl.DataFrame(rows))


# ---- position mapping -----------------------------------------------------

def test_maps_by_position_not_string(tmp_path):
    build = _build(tmp_path, GRID)
    # QuantAM "Part(2)" sits at (15,5) -> inside box "2"; "Part(1)" at (5,5) -> "1"
    q = _params({
        "Part ID": ["Part(1)", "Part(2)"],
        "X Position": [5.0, 15.0],
        "Y Position": [5.0, 5.0],
        "Hatch Speed": [800.0, 1200.0],
        "Hatches Power": [150, 200],
    })
    out = part_parameters(q, build)
    assert out.sort("part_id")["part_id"].to_list() == ["1", "2"]
    assert out.schema["part_id"] == pl.String
    assert set(out.columns) == {"part_id", *DEFAULT_PARAMETER_COLUMNS}
    assert out.filter(pl.col("part_id") == "2")["Hatch Speed"].to_list() == [1200.0]


def test_rename_columns():
    pass  # covered below with a build


def test_rename_for_friendly_headers(tmp_path):
    build = _build(tmp_path, GRID)
    q = _params({
        "Part ID": ["Part(1)"], "X Position": [5.0], "Y Position": [5.0],
        "Hatch Speed": [800.0], "Hatches Power": [150],
    })
    out = part_parameters(q, build, rename={"Hatch Speed": "speed", "Hatches Power": "power"})
    assert set(out.columns) == {"part_id", "speed", "power"}


def test_custom_columns(tmp_path):
    build = _build(tmp_path, GRID)
    q = _params({
        "Part ID": ["Part(1)"], "X Position": [5.0], "Y Position": [5.0],
        "Hatch Speed": [800.0], "Hatches Power": [150],
    })
    out = part_parameters(q, build, columns=("Hatches Power",))
    assert set(out.columns) == {"part_id", "Hatches Power"}
    assert "Hatch Speed" not in out.columns


# ---- warn-and-drop policy -------------------------------------------------

def test_unmatched_quant_row_dropped_with_warning(tmp_path, caplog):
    build = _build(tmp_path, GRID)
    q = _params({
        "Part ID": ["Part(1)", "Part(9)"],
        "X Position": [5.0, 999.0],       # second is off the plate
        "Y Position": [5.0, 999.0],
        "Hatch Speed": [800.0, 900.0],
        "Hatches Power": [150, 150],
    })
    with caplog.at_level("WARNING"):
        out = part_parameters(q, build)
    assert out["part_id"].to_list() == ["1"]         # off-plate row dropped
    assert "matched no build bounding box" in caplog.text


def test_build_part_without_quant_is_simply_absent(tmp_path):
    build = _build(tmp_path, GRID)   # parts 1 and 2 exist
    q = _params({
        "Part ID": ["Part(1)"], "X Position": [5.0], "Y Position": [5.0],
        "Hatch Speed": [800.0], "Hatches Power": [150],
    })
    out = part_parameters(q, build)
    # part 2 not in output; the template left-join is what null-fills it
    assert out["part_id"].to_list() == ["1"]


# ---- validation -----------------------------------------------------------

def test_missing_requested_column_raises(tmp_path):
    build = _build(tmp_path, GRID)
    q = _params({
        "Part ID": ["Part(1)"], "X Position": [5.0], "Y Position": [5.0],
        "Hatch Speed": [800.0], "Hatches Power": [150],
    })
    with pytest.raises(ParameterMappingError, match="not in QuantAM output"):
        part_parameters(q, build, columns=("Nonexistent Param",))


def test_missing_position_columns_raises(tmp_path):
    build = _build(tmp_path, GRID)
    q = _params({"Part ID": ["Part(1)"], "Hatch Speed": [800.0], "Hatches Power": [150]})
    with pytest.raises(ParameterMappingError, match="position-match"):
        part_parameters(q, build)


def test_overlapping_boxes_surface_as_duplicate(tmp_path):
    # two boxes overlapping at (7,7); a QuantAM point there would be ambiguous,
    # but a point inside only one still resolves. Force a dup by two rows mapping
    # to the same part.
    build = _build(tmp_path, GRID)
    q = _params({
        "Part ID": ["Part(1)a", "Part(1)b"],
        "X Position": [5.0, 6.0],        # both inside box "1"
        "Y Position": [5.0, 6.0],
        "Hatch Speed": [800.0, 810.0],
        "Hatches Power": [150, 150],
    })
    with pytest.raises(ParameterMappingError, match="same part_id"):
        part_parameters(q, build)


# ---- real pair, end-to-end ------------------------------------------------

@pytest.mark.skipif(not (REAL_CSV.exists() and REAL_DHXML.exists()),
                    reason="real QuantAM CSV + dhxml not present")
def test_real_jr299_end_to_end():
    build = BuildParts.from_dhxml(REAL_DHXML)
    out = part_parameters(REAL_CSV, build,
                          rename={"Hatch Speed": "speed", "Hatches Power": "power"})
    assert out.height == len(build) == 20
    assert out.schema["part_id"] == pl.String
    assert set(out.columns) == {"part_id", "speed", "power"}
    # position mapping must agree with the naive Part(N) strip on this unique build
    assert sorted(out["part_id"].to_list(), key=int) == [str(i) for i in range(1, 21)]
