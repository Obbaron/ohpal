"""Tests for the AggregateColumns action."""

from __future__ import annotations

import math
from pathlib import Path

import polars as pl
import pytest

from ohpal.samples.actions import AggregateColumns
from ohpal.samples.io import read_table
from ohpal.samples.recipe import Recipe, RecipeError

REAL = Path("/mnt/user-data/uploads/Archimedes_Density_TiAg.xlsx")


def _src(readings=3):
    data = {"id": ["p1", "p2", "p3"]}
    vals = [[2.0, 4.0, 6.0], [1.0, None, None], [None, None, None]]
    for i in range(readings):
        data[f"Density ({i + 1})"] = [row[i] if i < len(row) else None for row in vals]
    return pl.DataFrame(data)


def _recipe(df):
    return Recipe(df, key_column="id")


# ---- validation -----------------------------------------------------------

def test_requires_exactly_one_selector():
    with pytest.raises(RecipeError):
        AggregateColumns(out_prefix="density", stats=("avg",))  # neither
    with pytest.raises(RecipeError):
        AggregateColumns(out_prefix="density", stats=("avg",),
                         prefix="Density", columns=("a",))       # both


def test_unknown_stat_rejected_at_construction():
    with pytest.raises(Exception):
        AggregateColumns(out_prefix="d", stats=("bogus",), prefix="Density")


def test_empty_stats_rejected():
    with pytest.raises(RecipeError):
        AggregateColumns(out_prefix="d", stats=(), prefix="Density")


# ---- prefix (schema-tolerant) selection -----------------------------------

def test_prefix_avg_sd_sem_n():
    r = _recipe(_src(3)).do(
        AggregateColumns(out_prefix="density", stats=("avg", "sd", "sem", "n"),
                         prefix="Density", unit="g/cm3")
    )
    out = r.result()
    assert out["density_avg"].to_list() == [4.0, 1.0, None]
    assert out["density_sd"][0] == pytest.approx(2.0)
    assert out["density_sd"][1] is None                     # single reading
    assert out["density_sem"][0] == pytest.approx(2.0 / math.sqrt(3))
    assert out["density_n"].to_list() == [3, 1, 0]


def test_same_recipe_replays_on_different_reading_counts():
    # A recipe authored for 3 readings must also run on a 6-reading sheet.
    action = AggregateColumns(out_prefix="density", stats=("avg", "n"), prefix="Density")

    three = pl.DataFrame({"id": ["p1"], "Density (1)": [2.0], "Density (2)": [4.0], "Density (3)": [6.0]})
    six = pl.DataFrame({"id": ["p1"]} | {f"Density ({i})": [float(i)] for i in range(1, 7)})

    out3 = _recipe(three).do(action).result()
    out6 = _recipe(six).do(action).result()
    assert out3["density_n"][0] == 3 and out6["density_n"][0] == 6  # same recipe, both bind
    assert out3["density_avg"][0] == 4.0


def test_prefix_matching_nothing_raises():
    with pytest.raises(RecipeError, match="no columns match"):
        _recipe(_src(3)).do(
            AggregateColumns(out_prefix="x", stats=("avg",), prefix="Roughness")
        )


# ---- explicit columns -----------------------------------------------------

def test_explicit_columns():
    df = pl.DataFrame({"id": ["p1"], "m1": [10.0], "m2": [20.0], "m3": [30.0]})
    r = _recipe(df).do(
        AggregateColumns(out_prefix="mass", stats=("avg", "sum"), columns=("m1", "m2", "m3"))
    )
    out = r.result()
    assert out["mass_avg"].to_list() == [20.0]
    assert out["mass_sum"].to_list() == [60.0]


def test_missing_explicit_column_raises():
    df = pl.DataFrame({"id": ["p1"], "m1": [10.0]})
    with pytest.raises(RecipeError, match="not found"):
        _recipe(df).do(
            AggregateColumns(out_prefix="m", stats=("avg",), columns=("m1", "m2"))
        )


# ---- units / overwrite / provenance --------------------------------------

def test_units_value_stats_inherit_n_is_dimensionless():
    r = _recipe(_src(3)).do(
        AggregateColumns(out_prefix="density", stats=("avg", "sd", "n"),
                         prefix="Density", unit="g/cm3")
    )
    assert r.units_sidecar() == {"density_avg": "g/cm3", "density_sd": "g/cm3"}


def test_overwrite_guard():
    df = _src(3).with_columns(pl.lit(0.0).alias("density_avg"))
    with pytest.raises(RecipeError, match="overwrite"):
        _recipe(df).do(
            AggregateColumns(out_prefix="density", stats=("avg",), prefix="Density")
        )
    r = _recipe(df).do(
        AggregateColumns(out_prefix="density", stats=("avg",), prefix="Density", overwrite=True)
    )
    assert r.result()["density_avg"][0] == 4.0


def test_roundtrips_through_recipe_serialization():
    r = _recipe(_src(3)).do(
        AggregateColumns(out_prefix="density", stats=("avg", "sem"), prefix="Density", unit="g/cm3")
    )
    restored = Recipe.from_dict(_src(3), r.to_dict())
    assert restored.result().equals(r.result())
    assert restored.units_sidecar() == r.units_sidecar()


# ---- parity with summarize_readings on real data --------------------------

@pytest.mark.skipif(not REAL.exists(), reason="sample workbook not present")
def test_matches_summarize_readings_on_real_sheet():
    from ohpal.samples.analysis import summarize_readings

    df = read_table(REAL, sheet="Ti-6Ag")
    r = Recipe(df, key_column="Cube ID").do(
        AggregateColumns(out_prefix="density", stats=("avg", "sd", "n"), prefix="Density")
    )
    via_action = r.result()
    via_func = summarize_readings(df, prefix="Density")
    for col in ("density_avg", "density_sd", "density_n"):
        assert via_action[col].to_list() == via_func[col].to_list()
