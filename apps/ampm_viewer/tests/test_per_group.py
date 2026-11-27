"""One point per group on a 2D scatter (plotdata.build_per) and the trend
line (plotdata.linear_fit, fit_lines). No GUI or build needed."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest
from ampm_viewer.shell import plotdata
from ampm_viewer.shell.plotspec import MEAN_SD, SCATTER_2D, PlotSpec
from scipy import stats

# A signal per point and one measurement per specimen, as after Add from Excel.
RNG = np.random.default_rng(7)
SPECIMENS = {f"SP{i}": (200 + 4 * i, 10 + i, 1000 - 20 * i) for i in range(1, 9)}


def table() -> pl.DataFrame:
    rows = []
    for name, (mean, sd, dist) in SPECIMENS.items():
        for v in RNG.normal(mean, sd, 400 + 10 * int(name[2:])):
            rows.append({"alias": name, "Meltpool": float(v), "Distortion": dist,
                         "Group": "long" if int(name[2:]) <= 4 else "short"})
    rows.append({"alias": None, "Meltpool": 1e6, "Distortion": 0.0, "Group": None})
    rows.append({"alias": "noise", "Meltpool": 1e6, "Distortion": 0.0, "Group": None})
    return pl.DataFrame(rows)


def spec(**kw) -> PlotSpec:
    return PlotSpec(**{"kind": SCATTER_2D, "x": "Meltpool", "y": "Distortion",
                       "per": "alias", **kw})


def test_one_point_per_group_with_its_statistic():
    df = table()
    d = plotdata.build_per(df, spec(fit=True))
    rows = d.rows
    assert rows[plotdata.PER_GROUP].to_list() == list(SPECIMENS), "natural order, no null / noise"
    for name in SPECIMENS:
        r = rows.filter(pl.col(plotdata.PER_GROUP) == name).row(0, named=True)
        vals = df.filter(pl.col("alias") == name)["Meltpool"].to_numpy()
        assert r[plotdata.PER_X] == pytest.approx(vals.mean())
        assert r[plotdata.PER_Y] == SPECIMENS[name][2]
        assert r[plotdata.PER_N] == len(vals)
    assert d.labels == ("Mean of Meltpool", "Distortion"), "a per-group constant is named plainly"
    assert d.pos.shape == (8, 2) and not d.is_3d


@pytest.mark.parametrize("stat, fn", [
    ("median", np.median), ("sd", lambda v: np.std(v, ddof=1)),
    ("cov", lambda v: 100 * np.std(v, ddof=1) / np.mean(v)), ("min", np.min), ("max", np.max)])
def test_statistics(stat, fn):
    df = table()
    d = plotdata.build_per(df, spec(x_stat=stat))
    got = dict(zip(d.rows[plotdata.PER_GROUP].to_list(), d.rows[plotdata.PER_X].to_list()))
    for name in SPECIMENS:
        assert got[name] == pytest.approx(fn(df.filter(pl.col("alias") == name)["Meltpool"].to_numpy()))
    assert d.labels[0] == ("CoV of Meltpool (%)" if stat == "cov" else plotdata.stat_label(stat, "Meltpool"))


def test_colour_per_group():
    d = plotdata.build_per(table(), spec(color="Group"))
    assert [name for name, _ in d.legend] == ["long", "short"]
    d = plotdata.build_per(table().with_columns(pl.col("Distortion").alias("D2")), spec(color="D2"))
    assert d.legend[0] == "colorbar"


def test_fit_matches_scipy_and_label():
    x = np.array([200.0, 210, 222, 231, 245, 250])
    y = np.array([520.0, 610, 590, 700, 760, 830])
    f = plotdata.linear_fit(x, y)
    r = stats.linregress(x, y)
    assert (f.slope, f.intercept, f.p, f.n) == pytest.approx((r.slope, r.intercept, r.pvalue, 6))
    assert f.r2 == pytest.approx(r.rvalue ** 2)
    lines = plotdata.fit_lines(f, n=True)
    assert lines[0] == f"y = {plotdata._sig(r.slope)}x - {plotdata._sig(-r.intercept)}"
    assert lines[1] == f"R² = {r.rvalue ** 2:.2f}, p = {r.pvalue:.3f}, n = 6"
    assert plotdata.fit_lines(f, equation=False, r2=False, p=False) == []
    assert plotdata.p_text(1e-9) == "< 0.001"


def test_no_fit_without_spread():
    assert plotdata.linear_fit([1, 2], [3, 4]) is None, "two points: nothing to test"
    assert plotdata.linear_fit([5, 5, 5], [1, 2, 3]) is None, "X all equal"
    assert plotdata.linear_fit([1, np.nan, 2, 3], [1, 5, 2, 3]).n == 3, "non-finite dropped"


def test_fit_on_every_row_and_on_mean_sd():
    df = table()
    d = plotdata.build(df.filter(pl.col("alias").is_not_null() & (pl.col("alias") != "noise")),
                       PlotSpec(kind=SCATTER_2D, x="Meltpool", y="Distortion", fit=True))
    assert d.fit is not None and d.fit.n == d.n_total
    assert plotdata.build(df, PlotSpec(kind=SCATTER_2D, x="Meltpool", y="Distortion")).fit is None
    m = plotdata.build_meansd(df, PlotSpec(kind=MEAN_SD, x="Meltpool", y="Distortion",
                                           group_by="alias", fit=True), sample=None)
    r = stats.linregress(m.rows[plotdata.MS_X].to_numpy(), m.rows[plotdata.MS_MEAN].to_numpy())
    assert m.fit.slope == pytest.approx(r.slope)


def test_spec_round_trip_and_columns():
    s = spec(x_stat="cov", fit=True)
    assert s.is_per and s.is_grouped and s.can_fit and "alias" in s.columns
    t = PlotSpec(**{**s.__dict__})
    assert (t.per, t.x_stat, t.fit) == ("alias", "cov", True)
    assert not PlotSpec(kind=SCATTER_2D, x="a", y="b").is_per
    from ampm_viewer.shell.colref import rename_spec
    assert rename_spec(s, "alias", "Specimen").per == "Specimen"


def test_refuses_text_axes():
    with pytest.raises(ValueError, match="numeric"):
        plotdata.build_per(table(), spec(x="Group"))


# -- marker shape by a column, point labels, X error bars --------------------
def with_marks(df: pl.DataFrame) -> pl.DataFrame:
    """A per-specimen "Rotation" (three values) and a label column."""
    rot = {f"SP{i}": (0, 67, 90)[(i - 1) % 3] for i in range(1, 9)}
    return df.with_columns(
        pl.col("alias").replace_strict(rot, default=None).alias("Rotation"),
        pl.col("alias").str.replace("SP", "Specimen ").alias("Name"))


def test_shape_map_order_and_wrap():
    cats, shape = plotdata.shape_map(["b10", "b2", None, "b1"])
    assert cats == ["b1", "b2", "b10", plotdata.NO_VALUE], "natural order, no value last"
    assert [shape[c] for c in cats] == list(plotdata.SHAPES[:4])
    many = [f"c{i}" for i in range(len(plotdata.SHAPES) + 2)]
    _, shape = plotdata.shape_map(many)
    assert shape[f"c{len(plotdata.SHAPES)}"] == plotdata.SHAPES[0], "more than the shapes: round again"
    cats, _ = plotdata.shape_map([90.0, 0.0, 67.0, 22.5, float("nan")])
    assert cats == ["0", "22.5", "67", "90", plotdata.NO_VALUE], "whole numbers without .0"


def test_shapes_and_labels_per_group():
    df = with_marks(table())
    d = plotdata.build_per(df, spec(shape_by="Rotation", label_by="Name"))
    assert d.shape_legend == [("0", "disc"), ("67", "square"), ("90", "triangle_up")]
    want = {0: "disc", 67: "square", 90: "triangle_up"}
    for g, sym, text in zip(d.rows[plotdata.PER_GROUP], d.symbols, d.texts):
        r = df.filter(pl.col("alias") == g).row(0, named=True)
        assert sym == want[r["Rotation"]] and text == r["Name"], (g, sym, text)
    assert len(d.symbols) == len(d.texts) == len(d.pos)
    assert {"Rotation", "Name"} <= set(d.rows.columns), "kept for the tooltip"
    plain = plotdata.build_per(df, spec())
    assert plain.symbols is None and plain.shape_legend is None and plain.texts is None


def test_shapes_and_labels_on_every_row():
    df = with_marks(table()).filter(pl.col("alias").is_in(["SP1", "SP2"]))
    small = df.group_by("alias").head(20)
    d = plotdata.build(small, PlotSpec(kind=SCATTER_2D, x="Meltpool", y="Distortion",
                                       shape_by="Rotation", label_by="Meltpool"))
    assert d.n_drawn == 40 and len(d.symbols) == 40 and len(d.texts) == 40
    assert set(d.symbols) == {"disc", "square"}
    assert d.texts[0] == f"{d.rows['Meltpool'][0]:.4g}", "numbers to 4 significant figures"
    big = plotdata.build(df, PlotSpec(kind=SCATTER_2D, x="Meltpool", y="Distortion",
                                      label_by="Name"))
    assert big.n_drawn > plotdata.LABEL_MAX and big.texts is None, "too many to label"


def test_mean_sd_x_error_bars():
    df = with_marks(table())
    s = PlotSpec(kind=MEAN_SD, x="Meltpool", y="Distortion", group_by="Group",
                 x_error=True, shape_by="Rotation", label_by="Group")
    d = plotdata.build_meansd(df, s, sample="alias")
    for g, xe, ye in zip(d.rows[plotdata.MS_GROUP], d.err_x, d.err):
        per_part = (df.filter(pl.col("Group") == g).group_by("alias")
                    .agg(pl.col("Meltpool").mean(), pl.col("Distortion").mean()))
        assert xe == pytest.approx(np.std(per_part["Meltpool"].to_numpy(), ddof=1), rel=1e-5)
        assert ye == pytest.approx(np.std(per_part["Distortion"].to_numpy(), ddof=1), rel=1e-5)
    assert d.texts == ["long", "short"] and len(d.symbols) == 2
    se = plotdata.build_meansd(df, PlotSpec(**{**s.__dict__, "error": "se"}), sample="alias")
    n = se.rows[plotdata.MS_X_N].to_numpy()
    assert np.allclose(se.err_x, d.err_x / np.sqrt(n), rtol=1e-5), "the same error kind as Y"
    off = plotdata.build_meansd(df, PlotSpec(**{**s.__dict__, "x_error": False}), sample="alias")
    assert off.err_x is None
    one = plotdata.build_meansd(df, PlotSpec(**{**s.__dict__, "group_by": "alias"}), sample="alias")
    assert np.isnan(one.err_x).all(), "one part per group: no spread across"


def test_marks_follow_renames_and_macros():
    from ampm_viewer.shell import macros
    from ampm_viewer.shell import plot_elements as pe
    from ampm_viewer.shell.colref import rename_spec
    s = spec(shape_by="Rotation", label_by="Name")
    assert {"Rotation", "Name"} <= set(s.columns), "queried with the plot"
    r = rename_spec(rename_spec(s, "Rotation", "Build angle"), "Name", "Specimen")
    assert (r.shape_by, r.label_by) == ("Build angle", "Specimen")
    text = macros.describe("plot", {"spec": {**s.__dict__, "x_error": True}})
    assert "shape by 'Rotation'" in text and "labelled by 'Name'" in text and "X error bars" in text
    assert "labels" in pe.keys_for(s) and "labels" not in pe.keys_for(
        PlotSpec(kind="Histogram", x="a", y="count"))
    assert pe.builtin_style("labels", MEAN_SD)["side"] == "above_right", "clear of the error bars"
    assert pe.builtin_style("labels", SCATTER_2D)["side"] == "right"
