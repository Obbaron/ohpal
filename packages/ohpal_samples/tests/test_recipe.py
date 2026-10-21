"""Tests for the recipe engine and foundational actions."""

from __future__ import annotations

import polars as pl
import pytest

from ohpal.samples.actions import DeleteColumn, FillColumn, FormulaColumn, OverrideCell, RenameColumn
from ohpal.samples.recipe import (
    Action,
    IdentityGuardError,
    Recipe,
    RecipeError,
    action_from_dict,
)


def _src():
    return pl.DataFrame({"id": ["p1", "p2", "p3"], "mass": [10.0, 20.0, 30.0]})


# ---- construction / guard wiring ------------------------------------------

def test_key_column_must_exist():
    with pytest.raises(RecipeError):
        Recipe(_src(), key_column="part_id")  # source uses 'id'


def test_actions_conform_to_protocol():
    assert isinstance(FillColumn(column="c", value=1), Action)
    assert isinstance(OverrideCell(key_value="p1", column="mass", value=1.0), Action)


# ---- basic derivation -----------------------------------------------------

def test_fill_column_adds_constant():
    r = Recipe(_src(), key_column="id").do(FillColumn(column="temp", value=22.5, unit="degC"))
    out = r.result()
    assert out["temp"].to_list() == [22.5, 22.5, 22.5]
    assert r.units_sidecar() == {"temp": "degC"}


def test_source_never_mutated():
    src = _src()
    Recipe(src, key_column="id").do(DeleteColumn(column="mass"))
    assert "mass" in src.columns  # original untouched


# ---- phase ordering: overrides evaluate before derivations ----------------

def test_override_applies_before_derivation_regardless_of_record_order():
    # Record the rename FIRST, then an override targeting the *old* name.
    # Chronologically the override is last, but overrides run first, so it
    # patches 'mass' before the rename moves it to 'weight'.
    r = (
        Recipe(_src(), key_column="id")
        .do(RenameColumn(old="mass", new="weight"))
        .do(OverrideCell(key_value="p1", column="mass", value=99.0))
    )
    out = r.result()
    assert "weight" in out.columns and "mass" not in out.columns
    assert out.filter(pl.col("id") == "p1")["weight"].to_list() == [99.0]


def test_override_addresses_by_key_not_position():
    r = Recipe(_src(), key_column="id").do(OverrideCell(key_value="p2", column="mass", value=0.0))
    out = r.result()
    assert out.filter(pl.col("id") == "p2")["mass"].to_list() == [0.0]
    assert out.filter(pl.col("id") == "p1")["mass"].to_list() == [10.0]


def test_override_missing_key_raises():
    with pytest.raises(RecipeError, match="no row"):
        Recipe(_src(), key_column="id").do(OverrideCell(key_value="pX", column="mass", value=1.0))


# ---- identity guard -------------------------------------------------------

def test_delete_key_column_blocked():
    with pytest.raises(IdentityGuardError):
        Recipe(_src(), key_column="id").do(DeleteColumn(column="id"))


def test_delete_key_column_forced():
    r = Recipe(_src(), key_column="id").do(
        DeleteColumn(column="id", allow_identity_change=True)
    )
    assert "id" not in r.result().columns


def test_rename_key_column_blocked():
    with pytest.raises(IdentityGuardError):
        Recipe(_src(), key_column="id").do(RenameColumn(old="id", new="cube"))


def test_override_key_cell_blocked():
    with pytest.raises(IdentityGuardError):
        Recipe(_src(), key_column="id").do(OverrideCell(key_value="p1", column="id", value="pX"))


def test_override_key_cell_forced():
    r = Recipe(_src(), key_column="id").do(
        OverrideCell(key_value="p1", column="id", value="pX", allow_identity_change=True)
    )
    assert set(r.result()["id"].to_list()) == {"pX", "p2", "p3"}


def test_deleting_nonkey_column_is_fine():
    r = Recipe(_src(), key_column="id").do(DeleteColumn(column="mass"))
    assert r.result().columns == ["id"]


def test_failed_action_rolls_back():
    r = Recipe(_src(), key_column="id")
    with pytest.raises(IdentityGuardError):
        r.do(DeleteColumn(column="id"))
    assert r.actions == []  # recipe left clean
    assert r.result().columns == ["id", "mass"]


# ---- undo / redo ----------------------------------------------------------

def test_undo_redo_cursor():
    r = (
        Recipe(_src(), key_column="id")
        .do(FillColumn(column="a", value=1))
        .do(FillColumn(column="b", value=2))
        .do(FillColumn(column="c", value=3))
    )
    assert set(r.result().columns) == {"id", "mass", "a", "b", "c"}

    r.undo().undo()
    assert "b" not in r.result().columns and "a" in r.result().columns
    assert r.can_redo()

    r.redo()
    assert "b" in r.result().columns and "c" not in r.result().columns


def test_new_action_truncates_redo_tail():
    r = Recipe(_src(), key_column="id").do(FillColumn(column="a", value=1)).do(FillColumn(column="b", value=2))
    r.undo()                                 # b inactive
    r.do(FillColumn(column="d", value=4))    # should discard the redo tail (b)
    cols = r.result().columns
    assert "d" in cols and "b" not in cols
    assert not r.can_redo()


def test_undo_past_start_raises():
    r = Recipe(_src(), key_column="id")
    with pytest.raises(RecipeError):
        r.undo()


# ---- serialization (save / reload keeps undo history) ---------------------

def test_recipe_roundtrip_reproduces_frame():
    r = (
        Recipe(_src(), key_column="id")
        .do(FillColumn(column="temp", value=22.5, unit="degC"))
        .do(OverrideCell(key_value="p1", column="mass", value=11.0))
        .do(RenameColumn(old="mass", new="weight", unit="g"))
    )
    blob = r.to_dict()
    restored = Recipe.from_dict(_src(), blob)
    assert restored.result().equals(r.result())
    assert restored.units_sidecar() == {"temp": "degC", "weight": "g"}


def test_roundtrip_preserves_redo_tail():
    r = Recipe(_src(), key_column="id").do(FillColumn(column="a", value=1)).do(FillColumn(column="b", value=2))
    r.undo()  # 'b' is now a redo-tail entry
    restored = Recipe.from_dict(_src(), r.to_dict())
    assert "a" in restored.result().columns and "b" not in restored.result().columns
    assert restored.can_redo()
    restored.redo()
    assert "b" in restored.result().columns


def test_action_roundtrip():
    a = OverrideCell(key_value="p1", column="mass", value=5.0, allow_identity_change=False)
    assert action_from_dict(a.to_dict()) == a


def test_unknown_action_kind_raises():
    with pytest.raises(RecipeError, match="unknown action"):
        action_from_dict({"kind": "does_not_exist"})


# ---- FormulaColumn integration -------------------------------------------

def test_formula_column_in_recipe():
    r = Recipe(_src(), key_column="id").do(
        FormulaColumn(out="doubled", formula="([mass] + 3) * 2", unit="g")
    )
    out = r.result()
    assert out["doubled"].to_list() == [26.0, 46.0, 66.0]
    assert r.units_sidecar() == {"doubled": "g"}


def test_formula_bad_syntax_fails_at_construction():
    with pytest.raises(Exception):  # FormulaSyntaxError (fail-fast in __post_init__)
        FormulaColumn(out="x", formula="[mass] +")


def test_formula_overwrite_guard():
    r = Recipe(_src(), key_column="id")
    with pytest.raises(RecipeError, match="overwrite"):
        r.do(FormulaColumn(out="mass", formula="[mass] * 2"))
    r.do(FormulaColumn(out="mass", formula="[mass] * 2", overwrite=True))
    assert r.result()["mass"].to_list() == [20.0, 40.0, 60.0]


def test_formula_sees_override_first():
    # override corrects an input; the derived formula must see the corrected value
    r = (
        Recipe(_src(), key_column="id")
        .do(FormulaColumn(out="scaled", formula="[mass] * 10"))
        .do(OverrideCell(key_value="p1", column="mass", value=1.0))
    )
    out = r.result()
    # p1 mass corrected 10 -> 1 before the derivation, so scaled = 10, not 100
    assert out.filter(pl.col("id") == "p1")["scaled"].to_list() == [10.0]


def test_formula_roundtrips_through_recipe_serialization():
    r = Recipe(_src(), key_column="id").do(
        FormulaColumn(out="d", formula="mean([mass], [mass])", unit="g")
    )
    restored = Recipe.from_dict(_src(), r.to_dict())
    assert restored.result().equals(r.result())
