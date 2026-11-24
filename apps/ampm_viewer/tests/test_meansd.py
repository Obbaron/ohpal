"""The Mean ± SD plot's numbers (plotdata.build_meansd): one point per group,
each part counted once however many rows (measured points) it has, its
repeat columns pooled, sample SD / SE / 95% CI. No GUI or build needed."""

from __future__ import annotations

import math

import numpy as np
import polars as pl
import pytest
from ampm_viewer.shell import plotdata
from ampm_viewer.shell.plotspec import MEAN_SD, PlotSpec, default_spec

DENSITY = {"Part(1)": (4.50, 4.52, 4.51), "Part(2)": (4.40, 4.45, 4.35),
           "Part(3)": (4.55, 4.55, 4.55), "Part(4)": (4.30, None, 4.32)}
ENERGY = {"Part(1)": 100.0, "Part(2)": 60.0, "Part(3)": 100.0, "Part(4)": 400.0}


def table(points_per_part=500) -> pl.DataFrame:
    """Like the grid: a row per measured point, per-part columns repeated
    on each of a part's points, plus points in no part and DBSCAN noise."""
    rows = []
    for part, (a, b, c) in DENSITY.items():
        for i in range(points_per_part + int(part[-2])):  # unequal counts
            rows.append({"part_id": part, "E": ENERGY[part], "Density (1)": a,
                         "Density (2)": b, "Density (3)": c, "mp": float(i)})
    for part in (None, "noise"):
        rows.append({"part_id": part, "E": 5.0, "Density (1)": 1.0,
                     "Density (2)": 1.0, "Density (3)": 1.0, "mp": 0.0})
    return pl.DataFrame(rows)


def spec(**kw) -> PlotSpec:
    base = {"kind": MEAN_SD, "x": "E", "y": "Density (1)",
            "more_y": ("Density (2)", "Density (3)"), "group_by": "part_id"}
    return PlotSpec(**{**base, **kw})


def test_one_point_per_part_with_its_repeats():
    d = plotdata.build_meansd(table(), spec(), sample="part_id")
    got = {r[plotdata.MS_GROUP]: r for r in d.rows.iter_rows(named=True)}
    assert list(got) == ["Part(1)", "Part(2)", "Part(3)", "Part(4)"], "no noise, no null"
    for part, vals in DENSITY.items():
        vals = [v for v in vals if v is not None]
        r = got[part]
        assert r[plotdata.MS_N] == len(vals), "each part counts once per column"
        assert r[plotdata.MS_MEAN] == pytest.approx(np.mean(vals))
        assert r[plotdata.MS_X] == ENERGY[part]
        assert r[plotdata.MS_ERR] == pytest.approx(np.std(vals, ddof=1)), "sample SD"
    assert d.labels == ("E", "Density"), "the repeats share one axis name"
    assert d.pos.shape == (4, 2) and d.err.shape == (4,)


def test_error_kinds():
    sd = np.std(DENSITY["Part(2)"], ddof=1)
    for kind, want in (("se", sd / math.sqrt(3)),
                       ("ci95", 4.302653 * sd / math.sqrt(3))):
        d = plotdata.build_meansd(table(), spec(error=kind), sample="part_id")
        r = d.rows.filter(pl.col(plotdata.MS_GROUP) == "Part(2)")
        assert r[plotdata.MS_ERR][0] == pytest.approx(want, rel=1e-4), kind
    d = plotdata.build_meansd(table(), spec(error="none"), sample="part_id")
    assert np.isnan(d.err).all()
    assert plotdata.t95(2) == pytest.approx(4.3027, rel=1e-4)


def test_grouping_parts_pools_them_once_each():
    """Grouped by energy: Part(1) and Part(3) (both 100) pool, each part once,
    so 2 parts x 3 columns = 6 values, whatever their point counts."""
    d = plotdata.build_meansd(table(), spec(group_by="E"), sample="part_id")
    r = d.rows.filter(pl.col("E") == 100.0)
    vals = [*DENSITY["Part(1)"], *DENSITY["Part(3)"]]
    assert r[plotdata.MS_N][0] == 6
    assert r[plotdata.MS_MEAN][0] == pytest.approx(np.mean(vals))
    assert r[plotdata.MS_ERR][0] == pytest.approx(np.std(vals, ddof=1))
    assert 5.0 not in d.rows["E"].to_list(), "points in no part are left out"


def test_single_value_has_no_bar_and_colour_by_group():
    d = plotdata.build_meansd(table(), spec(more_y=(), color="part_id"),
                              sample="part_id")
    assert np.isnan(d.err).all(), "n = 1: no error bar"
    assert [name for name, _ in d.legend] == list(DENSITY)
    d = plotdata.build_meansd(table(), spec(color="mp"), sample="part_id")
    assert d.legend[0] == "colorbar"


def test_refuses_text_values_and_no_group():
    t = table().with_columns(pl.col("Density (1)").cast(pl.Utf8))
    with pytest.raises(ValueError, match="numeric"):
        plotdata.build_meansd(t, spec(), sample="part_id")
    with pytest.raises(ValueError, match="group"):
        plotdata.build_meansd(table(), spec(group_by=None), sample="part_id")


def test_spec_from_json_and_defaults():
    s = PlotSpec(**{**spec().__dict__, "more_y": ["Density (2)"]})
    assert s.more_y == ("Density (2)",) and s.values == ["Density (1)", "Density (2)"]
    assert "Density (2)" in s.columns
    d = default_spec(MEAN_SD, ["part_id", "Energy density", "Density (1)"])
    assert d.group_by == "part_id" and d.x == "Energy density" and d.error == "sd"


def test_value_label():
    assert plotdata.value_label(["Density (1)", "Density (2)"]) == "Density"
    assert plotdata.value_label(["Density_1", "Density_2"]) == "Density"
    assert plotdata.value_label(["a", "b"]) == "a, b"
    assert plotdata.value_label(["Density"]) == "Density"
