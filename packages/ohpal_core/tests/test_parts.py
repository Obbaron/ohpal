"""Tests for ohpal.core.parts (provider contract + merge)."""

from __future__ import annotations

import polars as pl
import pytest

from ohpal.core.parts import (
    PartAttributeProvider,
    MergeError,
    attribute_columns,
    merge,
    namespace_columns,
)


def _pid(ids):
    return pl.Series("part_id", ids, dtype=pl.String)


# ---- namespacing ----------------------------------------------------------

def test_namespace_prefixes_attributes_not_keys():
    df = pl.DataFrame({"part_id": _pid(["A"]), "build_id": ["b1"], "avg_density": [4.5]})
    out = namespace_columns(df, "samples")
    assert set(out.columns) == {"part_id", "build_id", "samples__avg_density"}


def test_namespace_is_idempotent():
    df = pl.DataFrame({"part_id": _pid(["A"]), "avg_density": [4.5]})
    once = namespace_columns(df, "samples")
    twice = namespace_columns(once, "samples")
    assert once.columns == twice.columns == ["part_id", "samples__avg_density"]


def test_attribute_columns_excludes_keys():
    df = pl.DataFrame({"build_id": ["b"], "part_id": _pid(["A"]), "cov": [0.1]})
    assert attribute_columns(df) == ["cov"]


# ---- merge: happy paths ---------------------------------------------------

def test_outer_join_keeps_all_parts():
    s = pl.DataFrame({"part_id": _pid(["1", "2", "3"]), "samples__d": [4.5, 4.4, 4.3]})
    a = pl.DataFrame({"part_id": _pid(["1", "2", "3", "4"]), "ampm__cov": [0.1, 0.2, 0.3, 0.4]})
    out = merge([s, a])  # default outer
    assert out["part_id"].to_list() == ["1", "2", "3", "4"]
    # part 4 has no samples measurement -> null, not dropped
    assert out.filter(pl.col("part_id") == "4")["samples__d"].to_list() == [None]


def test_inner_join_keeps_only_shared():
    s = pl.DataFrame({"part_id": _pid(["1", "2"]), "samples__d": [4.5, 4.4]})
    a = pl.DataFrame({"part_id": _pid(["1", "2", "3"]), "ampm__cov": [0.1, 0.2, 0.3]})
    out = merge([s, a], how="inner")
    assert out["part_id"].to_list() == ["1", "2"]


def test_single_frame_merges():
    s = pl.DataFrame({"part_id": _pid(["1"]), "samples__d": [4.5]})
    assert merge([s]).columns == ["part_id", "samples__d"]


def test_multi_build_key():
    s = pl.DataFrame({"build_id": ["b1", "b2"], "part_id": _pid(["1", "1"]), "samples__d": [4.5, 4.6]})
    a = pl.DataFrame({"build_id": ["b1", "b2"], "part_id": _pid(["1", "1"]), "ampm__cov": [0.1, 0.2]})
    out = merge([s, a])
    # same part_id "1" in two builds stays distinct
    assert out.height == 2
    assert set(out.columns) == {"build_id", "part_id", "samples__d", "ampm__cov"}


def test_single_build_mode_no_build_id():
    s = pl.DataFrame({"part_id": _pid(["1"]), "samples__d": [4.5]})
    a = pl.DataFrame({"part_id": _pid(["1"]), "ampm__cov": [0.1]})
    out = merge([s, a])
    assert "build_id" not in out.columns
    assert out.height == 1


# ---- merge: contract enforcement ------------------------------------------

def test_mixed_build_id_rejected():
    s = pl.DataFrame({"build_id": ["b1"], "part_id": _pid(["1"]), "samples__d": [4.5]})
    a = pl.DataFrame({"part_id": _pid(["1"]), "ampm__cov": [0.1]})  # no build_id
    with pytest.raises(MergeError, match="mixed build_id"):
        merge([s, a])


def test_attribute_collision_rejected():
    # both providers ship a bare 'density' — should have been namespaced
    s = pl.DataFrame({"part_id": _pid(["1"]), "density": [4.5]})
    a = pl.DataFrame({"part_id": _pid(["1"]), "density": [4.4]})
    with pytest.raises(MergeError, match="must namespace"):
        merge([s, a])


def test_non_utf8_part_id_rejected():
    s = pl.DataFrame({"part_id": [1, 2], "samples__d": [4.5, 4.4]})  # Int, not Utf8
    with pytest.raises(MergeError, match="must be Utf8"):
        merge([s])


def test_duplicate_key_rejected():
    s = pl.DataFrame({"part_id": _pid(["1", "1"]), "samples__d": [4.5, 4.4]})
    with pytest.raises(MergeError, match="duplicate key"):
        merge([s])


def test_null_part_id_rejected():
    s = pl.DataFrame({"part_id": _pid(["1", None]), "samples__d": [4.5, 4.4]})
    with pytest.raises(MergeError, match="null"):
        merge([s])


def test_empty_frames_list_rejected():
    with pytest.raises(MergeError):
        merge([])


def test_unknown_join_strategy_rejected():
    s = pl.DataFrame({"part_id": _pid(["1"]), "samples__d": [4.5]})
    with pytest.raises(MergeError, match="unknown join"):
        merge([s], how="cross")


# ---- provider protocol conformance ----------------------------------------

def test_provider_protocol_conformance():
    class SamplesProvider:
        name = "samples"

        def provide(self, build_id: str) -> pl.LazyFrame:
            return pl.DataFrame(
                {"build_id": [build_id], "part_id": _pid(["1"]), "samples__d": [4.5]}
            ).lazy()

    p = SamplesProvider()
    assert isinstance(p, PartAttributeProvider)
    # a real end-to-end: provider -> collect -> merge
    frame = p.provide("b1").collect()
    out = merge([frame])
    assert out["samples__d"].to_list() == [4.5]
