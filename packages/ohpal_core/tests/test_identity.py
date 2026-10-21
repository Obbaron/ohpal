"""Tests for ohpal.core.identity."""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

from ohpal.core.build import BuildParts, PartResolutionError
from ohpal.core.identity import (
    AmbiguousColumn,
    DirectColumnResolver,
    DuplicatePartId,
    IdentityError,
    NoApplicableResolver,
    PartIdentityResolver,
    SpatialBBoxResolver,
    default_resolvers,
    resolve_part_id,
)


def _build(tmp_path: Path) -> BuildParts:
    # Two unit squares with a gap, spanning z 0..10.
    doc = {"version1": {"build": {"parts": [
        {"name": "A", "boundingBox": "0,0,0,10,10,10"},
        {"name": "B", "boundingBox": "11,0,0,21,10,10"},
    ]}}}
    p = tmp_path / "BuildStarted.dhxml"
    p.write_text(json.dumps(doc), encoding="utf-8")
    return BuildParts.from_dhxml(p)


# ---- DirectColumnResolver -------------------------------------------------

@pytest.mark.parametrize("header", ["part_id", "Part ID", "PART-ID", "partid"])
def test_direct_matches_variants(header):
    df = pl.DataFrame({header: ["A", "B"], "density": [4.5, 4.4]})
    out = DirectColumnResolver().resolve(df)
    assert out["part_id"].to_list() == ["A", "B"]
    assert out.schema["part_id"] == pl.String


def test_direct_does_not_match_cube_id():
    df = pl.DataFrame({"Cube ID": [1, 2], "density": [4.5, 4.4]})
    assert DirectColumnResolver().applicable(df) is False


def test_direct_casts_int_ids_to_utf8():
    df = pl.DataFrame({"part_id": [1, 2, 3]})
    out = DirectColumnResolver().resolve(df)
    assert out["part_id"].to_list() == ["1", "2", "3"]


def test_direct_ambiguous_columns_raise():
    df = pl.DataFrame({"part id": ["A"], "part_id": ["A"]})
    with pytest.raises(AmbiguousColumn):
        DirectColumnResolver().applicable(df)


def test_direct_empty_column_is_not_applicable():
    df = pl.DataFrame({"part_id": [None, None], "x": [1.0, 2.0]}, )
    assert DirectColumnResolver().applicable(df) is False


def test_direct_partial_column_hard_fails():
    df = pl.DataFrame({"part_id": ["A", None]})
    with pytest.raises(IdentityError):
        DirectColumnResolver().resolve(df)


# ---- SpatialBBoxResolver --------------------------------------------------

def test_spatial_resolves_origins(tmp_path):
    build = _build(tmp_path)
    df = pl.DataFrame({"Cube ID": ["c1", "c2"], "X Position": [5.0, 15.0], "Y Position": [5.0, 5.0]})
    out = SpatialBBoxResolver(build).resolve(df)
    assert out["part_id"].to_list() == ["A", "B"]
    assert out["Cube ID"].to_list() == ["c1", "c2"]  # alias preserved alongside


def test_spatial_applicable_needs_both_axes(tmp_path):
    build = _build(tmp_path)
    assert SpatialBBoxResolver(build).applicable(pl.DataFrame({"x": [1.0]})) is False
    assert SpatialBBoxResolver(build).applicable(pl.DataFrame({"x": [1.0], "y": [2.0]})) is True


def test_spatial_ambiguous_origin_raises(tmp_path):
    build = _build(tmp_path)
    df = pl.DataFrame({"x": [10.5], "y": [5.0]})  # in the gap, no box
    with pytest.raises(PartResolutionError):
        SpatialBBoxResolver(build).resolve(df)


# ---- chain runner ---------------------------------------------------------

def test_chain_prefers_direct_over_spatial(tmp_path):
    build = _build(tmp_path)
    # part_id present but coords would resolve differently — direct must win.
    df = pl.DataFrame({"part_id": ["B", "A"], "x": [5.0, 15.0], "y": [5.0, 5.0]})
    out = resolve_part_id(df, default_resolvers(build))
    assert out["part_id"].to_list() == ["B", "A"]  # from the column, not the coords


def test_chain_falls_to_spatial_when_no_column(tmp_path):
    build = _build(tmp_path)
    df = pl.DataFrame({"Cube ID": ["c1"], "x": [5.0], "y": [5.0]})
    out = resolve_part_id(df, default_resolvers(build))
    assert out["part_id"].to_list() == ["A"]


def test_chain_first_applicable_owns_failure(tmp_path):
    build = _build(tmp_path)
    # Direct is applicable (one non-null id) but has a hole -> hard fail,
    # even though spatial could have resolved every row from coords.
    df = pl.DataFrame({"part_id": ["A", None], "x": [5.0, 15.0], "y": [5.0, 5.0]})
    with pytest.raises(IdentityError):
        resolve_part_id(df, default_resolvers(build))


def test_chain_no_applicable_resolver(tmp_path):
    build = _build(tmp_path)
    df = pl.DataFrame({"Cube ID": ["c1"], "density": [4.5]})  # alias only, no key, no coords
    with pytest.raises(NoApplicableResolver):
        resolve_part_id(df, default_resolvers(build))


def test_require_unique_rejects_duplicate_keys():
    df = pl.DataFrame({"part_id": ["A", "A", "B"]})
    with pytest.raises(DuplicatePartId):
        resolve_part_id(df, [DirectColumnResolver()], require_unique=True)


def test_direct_only_chain_without_build():
    df = pl.DataFrame({"part_id": ["A"]})
    out = resolve_part_id(df, default_resolvers())  # no build -> direct only
    assert out["part_id"].to_list() == ["A"]


# ---- conformance seam for the future ampm-cluster resolver ----------------

def test_external_resolver_conforms_to_protocol():
    """Proves a resolver defined outside core (e.g. ohpal.ampm's cluster
    resolver) slots into the chain by satisfying the runtime-checkable
    protocol — the seam that keeps core from importing ampm."""

    class FakeClusterResolver:
        name = "ampm_cluster"

        def applicable(self, df: pl.DataFrame) -> bool:
            return "cluster" in df.columns

        def resolve(self, df: pl.DataFrame) -> pl.DataFrame:
            return df.with_columns(pl.col("cluster").cast(pl.String).alias("part_id"))

    resolver = FakeClusterResolver()
    assert isinstance(resolver, PartIdentityResolver)

    df = pl.DataFrame({"cluster": [1, 2], "signal": [0.1, 0.2]})
    out = resolve_part_id(df, [DirectColumnResolver(), resolver])
    assert out["part_id"].to_list() == ["1", "2"]
