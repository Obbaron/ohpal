"""Tests for ohpal.samples.formula — including hostile inputs proving the boundary."""

from __future__ import annotations

import math

import polars as pl
import pytest

from ohpal.samples.formula import (
    FormulaColumnError,
    FormulaError,
    FormulaSecurityError,
    FormulaSyntaxError,
    compile_formula,
    evaluate,
    parse_formula,
)


def _df():
    return pl.DataFrame({
        "a": [1.0, 2.0, 3.0],
        "b": [4.0, 0.0, 2.0],
        "mass in air": [10.0, 20.0, 30.0],
        "Density (1)": [4.5, 4.4, None],
        "Density (2)": [4.6, None, None],
        "Density (3)": [4.7, None, None],
    })


# ---- parsing / column discovery (data-free) -------------------------------

def test_columns_known_without_data():
    p = parse_formula("([mass in air] - [b]) / [a]")
    assert p.columns == {"mass in air", "b", "a"}


def test_bracket_names_with_symbols():
    p = parse_formula("[Density AVG (g/cm^3)] * 2")
    assert p.columns == {"Density AVG (g/cm^3)"}


def test_empty_reference_rejected():
    with pytest.raises(FormulaSyntaxError):
        parse_formula("[] + 1")


def test_syntax_error():
    with pytest.raises(FormulaSyntaxError):
        parse_formula("[a] + ")


# ---- arithmetic -----------------------------------------------------------

def test_basic_arithmetic():
    out = evaluate("([a] + 3) * 2", _df())
    assert out.to_list() == [8.0, 10.0, 12.0]


def test_column_algebra():
    out = evaluate("[mass in air] / [a]", _df())
    assert out.to_list() == [10.0, 10.0, 10.0]


def test_power_and_unary_minus():
    out = evaluate("-[a] ** 2", _df())
    assert out.to_list() == [-1.0, -4.0, -9.0]


def test_constants():
    out = evaluate("[a] * pi", _df())
    assert out.to_list() == pytest.approx([math.pi, 2 * math.pi, 3 * math.pi])


# ---- functions ------------------------------------------------------------

def test_unary_functions():
    assert evaluate("sqrt([b])", _df()).to_list() == [2.0, 0.0, pytest.approx(2**0.5)]


def test_round_with_literal_places():
    assert evaluate("round([a] / 3, 2)", _df()).to_list() == [0.33, 0.67, 1.0]


def test_round_non_literal_places_rejected():
    with pytest.raises(FormulaError, match="integer literal"):
        evaluate("round([a], [b])", _df())


def test_horizontal_mean_skips_nulls():
    # row0 has 3 readings, row1 has 1, row2 has 0
    out = evaluate("mean([Density (1)], [Density (2)], [Density (3)])", _df())
    assert out[0] == pytest.approx(4.6)
    assert out[1] == 4.4
    assert out[2] is None


def test_sem_matches_definition():
    df = pl.DataFrame({"x": [2.0], "y": [4.0], "z": [6.0]})
    got = evaluate("sem([x], [y], [z])", df)[0]
    assert got == pytest.approx(2.0 / math.sqrt(3))  # std=2, n=3


# ---- null / non-finite policy --------------------------------------------

def test_div_by_zero_is_null():
    out = evaluate("[a] / [b]", _df())          # b[1] == 0
    assert out[0] == 0.25
    assert out[1] is None                        # 2/0 -> inf -> null
    assert out[2] == 1.5


def test_null_propagates_in_arithmetic():
    out = evaluate("[Density (1)] + [Density (2)]", _df())
    assert out[0] == pytest.approx(9.1)
    assert out[1] is None                        # null + number -> null


# ---- schema boundary ------------------------------------------------------

def test_unknown_column_raises_at_compile():
    p = parse_formula("[nope] + 1")
    with pytest.raises(FormulaColumnError, match="unknown column"):
        compile_formula(p, _df().columns)


# ---- SECURITY BOUNDARY: hostile inputs must be rejected -------------------

@pytest.mark.parametrize("hostile", [
    "__import__('os')",
    "[a].__class__",
    "[a].__class__.__mro__",
    "lambda: 1",
    "[a] if [b] else 0",
    "[a] and [b]",
    "[a] == [b]",
    "[a] > 1",
    "not [a]",
    "open('x')",
    "exec('y')",
    "foo([a])",
    "'string'",
    "[a] & 1",
    "[a] << 2",
])
def test_hostile_inputs_rejected(hostile):
    with pytest.raises(FormulaSecurityError):
        parse_formula(hostile)


def test_reserved_placeholder_token_rejected():
    with pytest.raises(FormulaSecurityError, match="reserved"):
        parse_formula("_ohpalcol_0 + 1")


def test_code_cannot_hide_inside_brackets():
    # bracket contents are raw column names, never parsed as code
    p = parse_formula("[__import__('os')]")
    assert p.columns == {"__import__('os')"}      # treated as a (bogus) column name
    with pytest.raises(FormulaColumnError):
        compile_formula(p, _df().columns)
