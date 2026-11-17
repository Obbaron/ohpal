"""
Tests for ``stacked.py``: several builds read as one continuous (stepped)
build. Two small synthetic step builds, each numbered from layer 1.
"""

from __future__ import annotations

import polars as pl
import pytest

from ohpal.ampm.datastore import DataStore
from ohpal.ampm.stacked import (
    BUILD_TIME, STEP, StackedStore, is_stack, load_stack, read_stack, write_stack)

from test_datastore import write_layer_file

N_ROWS = 8          # rows per layer; Start time runs 1000..1007 us, Duration 5
LAYER_END = 1007 + 5


def _step(tmp_path, name, layers, thickness):
    root = tmp_path / name
    # Bracketed, like a real export folder (Polars would glob it).
    src = root / "[3] Export Packets"
    src.mkdir(parents=True)
    for L in layers:
        write_layer_file(src, L, n_rows=N_ROWS)
    (root / "config.toml").write_text(
        f"[paths]\nsource = '{src.name}'\n\n[build]\n"
        f"layer_thickness = {thickness}\n", encoding="utf-8")
    return root, DataStore(src, layer_thickness=thickness)


@pytest.fixture
def stack(tmp_path):
    a_root, a = _step(tmp_path, "s1", [1, 2, 3], 0.03)
    b_root, b = _step(tmp_path, "s2", [1, 2], 0.05)
    return StackedStore([(a_root, a, {}), (b_root, b, {})],
                        cache_dir=tmp_path / "stack" / ".cache", name="JR")


def test_layers_continue_from_step_to_step(stack):
    assert stack.layers == [1, 2, 3, 4, 5]
    assert [s.layer_offset for s in stack.steps] == [0, 3]
    assert stack.step_of(4).index == 2 and stack.step_of(4).local(4) == 1


def test_query_continues_layer_z_and_build_time(stack):
    df = stack.query(layers=(1, 5)).sort(["layer", "Start time"])
    assert df["layer"].unique().sort().to_list() == [1, 2, 3, 4, 5]
    z = dict(df.group_by("layer").agg(pl.col("Z").first()).iter_rows())
    # 3 layers at 0.03 mm, then step 2's own layers at 0.05 mm on top.
    assert z[3] == pytest.approx(0.09) and z[4] == pytest.approx(0.14)
    assert z[5] == pytest.approx(0.19)
    steps = dict(df.group_by("layer").agg(pl.col(STEP).first()).iter_rows())
    assert steps == {1: 1, 2: 1, 3: 1, 4: 2, 5: 2}
    t0 = dict(df.group_by("layer").agg(pl.col(BUILD_TIME).min()).iter_rows())
    # Each layer starts where the one below ended: no restart at a step.
    for L in (2, 3, 4, 5):
        assert t0[L] == pytest.approx(t0[L - 1] + LAYER_END / 1e6)
    assert t0[1] == pytest.approx(1000 / 1e6)


def test_columns_and_selection(stack):
    assert stack.columns[-2:] == [STEP, BUILD_TIME]
    df = stack.query(layers=(3, 4), columns=["Demand X", BUILD_TIME])
    assert set(df.columns) == {"Demand X", BUILD_TIME, "layer", "Z"}, df.columns
    assert df["layer"].unique().sort().to_list() == [3, 4]
    df = stack.query(layers=[5], columns=["Demand X"])
    assert "Start time" not in df.columns and df["layer"].unique().to_list() == [5]


def test_part_ids_take_the_step(stack):
    table = pl.DataFrame({"part_id": ["Part(1)"], "x_min": [-1.0], "x_max": [100.0],
                          "y_min": [-1.0], "y_max": [100.0]})
    stack.set_step_part_assignment(1, table, method="bbox")
    assert "part_id" not in stack.columns, "only when every step has parts"
    stack.set_step_part_assignment(2, table, method="bbox")
    df = stack.query(layers=(3, 4), columns=["part_id"])
    ids = dict(df.group_by("layer").agg(pl.col("part_id").first()).iter_rows())
    assert ids == {3: "S1 Part(1)", 4: "S2 Part(1)"}


def test_sampling_is_shared_across_steps(stack):
    df = stack.query(sample_to=10)
    assert 0 < df.height <= 5 * N_ROWS and df["layer"].n_unique() >= 2


def test_cache_and_mask_by_stacked_layer(stack):
    assert stack.cached_layers() == set()
    stack.build_cache(layers=[2, 4], verbose=False)
    assert stack.cached_layers() == {2, 4}
    assert stack.stacked_mask(stack.steps[1], {1: "poly"}) == {4: "poly"}


def test_build_time_layer_ends_are_cached(stack, tmp_path):
    stack.query(layers=(1, 5))
    assert (tmp_path / "stack" / ".cache" / "layer_times.json").is_file()
    # A store opened later reads them back and gives the same clock.
    again = StackedStore([(s.root, s.store, {}) for s in stack.steps],
                         cache_dir=tmp_path / "stack" / ".cache")
    a = stack.query(layers=[5], columns=[BUILD_TIME])[BUILD_TIME].min()
    b = again.query(layers=[5], columns=[BUILD_TIME])[BUILD_TIME].min()
    assert a == pytest.approx(b)


def test_stack_file_round_trip(tmp_path, stack):
    folder = tmp_path / "stack"
    write_stack(folder, "JR stacked", [tmp_path / "s1", tmp_path / "s2"])
    assert is_stack(folder) and not is_stack(tmp_path / "s1")
    assert "../s1" in (folder / "stacked.toml").read_text(encoding="utf-8")
    name, roots = read_stack(folder)
    assert name == "JR stacked" and roots == [tmp_path / "s1", tmp_path / "s2"]
    store = load_stack(folder)
    assert store.layers == [1, 2, 3, 4, 5] and store.cache_dir == folder / ".cache"
    assert [s.thickness for s in store.steps] == [0.03, 0.05]


def test_the_bottom_step_keeps_its_numbering(tmp_path):
    a_root, a = _step(tmp_path, "s1", [3, 4], 0.03)
    b_root, b = _step(tmp_path, "s2", [1, 2], 0.03)
    stack = StackedStore([(a_root, a, {}), (b_root, b, {})],
                         cache_dir=tmp_path / "stack" / ".cache")
    assert stack.layers == [3, 4, 5, 6]
    z = dict(stack.query(columns=["Demand X"]).group_by("layer")
             .agg(pl.col("Z").first()).iter_rows())
    assert z[3] == pytest.approx(0.09) and z[5] == pytest.approx(0.15)


def test_a_stack_needs_two_steps(tmp_path):
    write_stack(tmp_path / "one", "x", [tmp_path])
    with pytest.raises(ValueError, match="two steps"):
        read_stack(tmp_path / "one")
