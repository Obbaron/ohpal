"""Tests for ohpal.samples.analysis.summarize_readings."""

from __future__ import annotations

import math
from pathlib import Path

import polars as pl
import pytest

from ohpal.samples.analysis import (
    NoReadingColumns,
    find_reading_columns,
    summarize_readings,
)
from ohpal.samples.io import read_table

REAL = Path("/mnt/user-data/uploads/Archimedes_Density_TiAg.xlsx")


# ---- detection ------------------------------------------------------------

def test_finds_parenthesised_and_bare_variants():
    df = pl.DataFrame({"Density (1)": [1.0], "Density (2)": [1.0], "Density (3)": [1.0]})
    assert find_reading_columns(df, "Density") == ["Density (1)", "Density (2)", "Density (3)"]
    df2 = pl.DataFrame({"Density 1": [1.0], "Density 2": [1.0]})
    assert find_reading_columns(df2, "Density") == ["Density 1", "Density 2"]


def test_ordered_by_number_not_position():
    df = pl.DataFrame({"Density (3)": [1.0], "Density (1)": [1.0], "Density (2)": [1.0]})
    assert find_reading_columns(df, "Density") == ["Density (1)", "Density (2)", "Density (3)"]


def test_does_not_match_avg_or_unrelated():
    df = pl.DataFrame({"Density AVG (g/cm^3)": [1.0], "Density (1)": [1.0], "Speed": [1.0]})
    assert find_reading_columns(df, "Density") == ["Density (1)"]


# ---- summary maths --------------------------------------------------------

def test_avg_sd_n_basic():
    df = pl.DataFrame({"Density (1)": [2.0], "Density (2)": [4.0], "Density (3)": [6.0]})
    out = summarize_readings(df)
    assert out["density_avg"].to_list() == [4.0]
    assert out["density_sd"].to_list() == [pytest.approx(2.0)]   # sample sd of 2,4,6
    assert out["density_n"].to_list() == [3]


def test_ragged_readings_skip_nulls():
    df = pl.DataFrame({"Density 1": [1.0, 2.0], "Density 2": [3.0, None], "Density 3": [5.0, None]})
    out = summarize_readings(df)
    assert out["density_avg"].to_list() == [3.0, 2.0]
    assert out["density_n"].to_list() == [3, 1]
    assert out["density_sd"][1] is None            # single reading -> null sd


def test_all_blank_row_is_null():
    df = pl.DataFrame({"Density 1": [None], "Density 2": [None]}, schema={"Density 1": pl.Float64, "Density 2": pl.Float64})
    out = summarize_readings(df)
    assert out["density_avg"][0] is None
    assert out["density_n"].to_list() == [0]


def test_custom_out_prefix_and_ddof():
    df = pl.DataFrame({"Mass 1": [1.0], "Mass 2": [3.0]})
    out = summarize_readings(df, prefix="Mass", out_prefix="mass", ddof=0)
    assert out["mass_avg"].to_list() == [2.0]
    assert out["mass_sd"].to_list() == [pytest.approx(1.0)]  # population sd of 1,3


def test_no_matching_prefix_raises():
    df = pl.DataFrame({"Speed": [1.0]})
    with pytest.raises(NoReadingColumns):
        summarize_readings(df, prefix="Density")


def test_original_columns_preserved():
    df = pl.DataFrame({"Cube ID": ["1"], "Density 1": [2.0], "Density 2": [4.0]})
    out = summarize_readings(df)
    assert "Cube ID" in out.columns and "Density 1" in out.columns


# ---- real workbook: recompute independent of the human's AVG --------------

@pytest.mark.skipif(not REAL.exists(), reason="sample workbook not present")
def test_real_recompute_matches_human_avg_within_tolerance():
    df = read_table(REAL, sheet="Ti-6Ag")
    out = summarize_readings(df)
    # our recomputed avg should track the human's in-sheet Density AVG closely
    human = out["Density AVG (g/cm^3)"]
    ours = out["density_avg"]
    diffs = [abs(a - b) for a, b in zip(human.to_list(), ours.to_list()) if a is not None and b is not None]
    assert diffs and max(diffs) < 1e-3
