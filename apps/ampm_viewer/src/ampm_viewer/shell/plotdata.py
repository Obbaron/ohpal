"""Turn (DataFrame, PlotSpec) into render-ready arrays.

Pure data — no Qt, no VisPy — so it's testable on its own and the plot tab just
feeds the result to a canvas. Handles any column on any channel:

* axis columns → float positions; a non-numeric axis is factorised to codes.
* colour: none → one colour; numeric → a colormap over its range; non-numeric
  (e.g. a group label) → a discrete palette with a legend.

Rows with a null/non-finite value on any *axis* are dropped. If the result is
larger than ``max_points`` it is randomly decimated (seeded, reproducible) so
plots stay responsive while the grid keeps every row via virtualisation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

# Colormap stops (RGB 0..1), linearly interpolated for numeric colour. The
# diverging BlueRed / RedBlue (a coolwarm) are the defaults for signal data.
_COLORMAPS = {
    "BlueRed": [[0.230, 0.299, 0.754], [0.865, 0.865, 0.865], [0.706, 0.016, 0.150]],
    "RedBlue": [[0.706, 0.016, 0.150], [0.865, 0.865, 0.865], [0.230, 0.299, 0.754]],
    "viridis": [
        [0.267, 0.005, 0.329], [0.283, 0.141, 0.458], [0.254, 0.265, 0.530],
        [0.207, 0.372, 0.553], [0.164, 0.471, 0.558], [0.128, 0.567, 0.551],
        [0.135, 0.659, 0.518], [0.267, 0.749, 0.441], [0.741, 0.873, 0.150],
    ],
    "plasma": [
        [0.050, 0.030, 0.528], [0.417, 0.000, 0.658], [0.692, 0.165, 0.564],
        [0.881, 0.392, 0.383], [0.988, 0.652, 0.211], [0.940, 0.975, 0.131],
    ],
    "magma": [
        [0.001, 0.000, 0.014], [0.232, 0.059, 0.437], [0.550, 0.161, 0.506],
        [0.868, 0.288, 0.409], [0.994, 0.624, 0.427], [0.987, 0.991, 0.749],
    ],
    "turbo": [
        [0.190, 0.072, 0.232], [0.275, 0.408, 0.859], [0.149, 0.740, 0.757],
        [0.531, 0.941, 0.293], [0.912, 0.755, 0.180], [0.890, 0.267, 0.079],
        [0.479, 0.012, 0.011],
    ],
    "turbo_r": [
        [0.479, 0.012, 0.011], [0.890, 0.267, 0.079], [0.912, 0.755, 0.180],
        [0.531, 0.941, 0.293], [0.149, 0.740, 0.757], [0.275, 0.408, 0.859],
        [0.190, 0.072, 0.232],
    ],
}
COLORMAP_NAMES = tuple(_COLORMAPS)
DEFAULT_COLORMAP = "turbo"  # no white midpoint → data stays visible on white bg
_LUTS = {name: np.array(stops, dtype="float32") for name, stops in _COLORMAPS.items()}


def colormap_stops(name: str) -> list:
    """The RGB control points for a colormap (for building a VisPy Colormap)."""
    return _COLORMAPS.get(name, _COLORMAPS[DEFAULT_COLORMAP])
# Discrete palette for categorical colour (Okabe–Ito, colour-blind-safe).
_CATEGORICAL = np.array(
    [
        [0.90, 0.62, 0.00], [0.34, 0.71, 0.91], [0.00, 0.62, 0.45],
        [0.95, 0.90, 0.25], [0.00, 0.45, 0.70], [0.84, 0.37, 0.00],
        [0.80, 0.47, 0.65], [0.40, 0.40, 0.40],
    ],
    dtype="float32",
)
_SOLID = (0.35, 0.60, 0.95, 1.0)  # default single colour (opaque)
_NULL_RGBA = (0.45, 0.47, 0.52, 0.55)  # colour for null values in a colour column


@dataclass
class RenderData:
    pos: np.ndarray            # (N, 2) or (N, 3) float32
    colors: np.ndarray         # (N, 4) float32
    is_3d: bool
    labels: tuple              # (x, y) or (x, y, z) axis names
    legend: Any                # None | [(label, (r,g,b,a))] | ("colorbar", lo, hi, name)
    n_total: int               # rows after null-drop, before decimation
    n_drawn: int               # rows actually in pos
    crange: tuple | None = None  # (lo, hi) used for numeric colour, for the sliders
    full_range: tuple | None = None  # (min, max) of the colour column, for Min/Max
    rows: Any = None           # the drawn subset (polars DataFrame) for hover lookup
    err: Any = None            # mean-sd: (N,) error bar half-heights (NaN: none)


@dataclass
class BarData:
    centers: np.ndarray   # (N,) x position of each bar's centre
    heights: np.ndarray   # (N,) float32 bar height
    colors: np.ndarray    # (N, 4) float32
    value_name: str       # y-axis / colourbar label
    x_name: str           # x-axis label
    labels: list | None   # category labels (bar) or None (histogram)
    categorical: bool     # True → category axis (labels); False → numeric x
    width: float = 0.8    # bar width in data units
    crange: tuple | None = None
    full_range: tuple | None = None
    n: int = 0


def _bar_colors(heights, cmap, crange):
    """Colour each bar by its height via the colormap; returns (colors, lo, hi)."""
    finite = np.isfinite(heights)
    if crange is not None:
        lo, hi = float(crange[0]), float(crange[1])
    elif finite.any():
        lo, hi = float(np.min(heights[finite])), float(np.max(heights[finite]))
    else:
        lo, hi = 0.0, 1.0
    span = (hi - lo) or 1.0
    t = np.where(finite, (heights - lo) / span, 0.0).astype("float32")
    colors = _apply_cmap(t, cmap)
    colors[~finite] = _NULL_RGBA
    return colors, lo, hi


def build_bars(df, spec, *, cmap=None, scale="linear", crange=None) -> BarData:
    """Aggregate ``spec.y`` per category ``spec.x`` into one bar each."""
    import polars as pl

    cmap = cmap or DEFAULT_COLORMAP
    cat, val, agg = spec.x, spec.y, (spec.agg or "mean")
    for c in (cat, val):
        if c and c not in df.columns:
            raise KeyError(f"Column {c!r} is not in the data.")

    rows = df.filter(pl.col(cat).is_not_null())
    if agg == "as-is":
        # The value is already one-per-category (e.g. a metric derived
        # ``by [region]``), so take it directly instead of reducing every row.
        # Guard: a category that actually carries differing values would be
        # silently mis-summarised, so flag it and point at a real aggregate.
        g = (
            rows.group_by(cat, maintain_order=True)
            .agg(pl.col(val).first().alias("_v"),
                 pl.col(val).n_unique().alias("_nu"))
            .sort(cat)
        )
        bad = g.filter(pl.col("_nu") > 1)[cat].to_list()
        if bad:
            shown = ", ".join(str(b) for b in bad[:3])
            more = "" if len(bad) <= 3 else f" (+{len(bad) - 3} more)"
            raise ValueError(
                f"“as-is” expects a single {val} per {cat}, but these carry "
                f"several: {shown}{more}. Pick an aggregate (mean, median, …)."
            )
    else:
        reduce = {
            "mean": pl.col(val).mean(), "median": pl.col(val).median(),
            "sum": pl.col(val).sum(), "min": pl.col(val).min(),
            "max": pl.col(val).max(), "count": pl.len(),
            "first": pl.col(val).first(),
        }.get(agg, pl.col(val).mean())
        g = (
            rows.group_by(cat, maintain_order=True)
            .agg(reduce.alias("_v"))
            .sort(cat)
        )
    labels = [str(v) for v in g[cat].to_list()]
    heights = g["_v"].to_numpy().astype("float32")
    labels, heights = _sort_bars(labels, heights, spec.sort)
    colors, lo, hi = _bar_colors(heights, cmap, crange)
    n = len(labels)
    return BarData(np.arange(n, dtype="float32"), heights, colors, val, cat,
                   labels, True, 0.8, (lo, hi), (lo, hi), n)


def _natural_key(value) -> tuple:
    """Sort text the way people count: "Part(2)" before "Part(10)"."""
    import re

    parts = re.split(r"(\d+)", "" if value is None else str(value))
    return tuple((0, int(p), "") if p.isdigit() else (1, 0, p.lower())
                 for p in parts if p)


def _sort_bars(labels: list, heights: np.ndarray, how: str | None):
    """Bars in name order (as grouped), or tallest first ("value"); bars with
    no value go last."""
    if how != "value" or len(labels) < 2:
        return labels, heights
    key = np.where(np.isfinite(heights), -heights.astype("float64"), np.inf)
    order = np.argsort(key, kind="stable")
    return [labels[i] for i in order], heights[order]


def build_histogram(df, spec, *, cmap=None, scale="linear", crange=None) -> BarData:
    """Bin numeric ``spec.x`` into ``spec.bins`` bars of counts."""
    cmap = cmap or DEFAULT_COLORMAP
    col = spec.x
    if col and col not in df.columns:
        raise KeyError(f"Column {col!r} is not in the data.")

    vals = df[col].to_numpy().astype("float64")
    vals = vals[np.isfinite(vals)]
    if vals.size == 0:
        empty = np.zeros((0, 4), "float32")
        return BarData(np.zeros(0, "float32"), np.zeros(0, "float32"), empty,
                       "count", col, None, False, 0.0, None, None, 0)
    bins = max(1, int(spec.bins or 30))
    counts, edges = np.histogram(vals, bins=bins)
    centers = ((edges[:-1] + edges[1:]) / 2).astype("float32")
    width = float(edges[1] - edges[0]) if len(edges) > 1 else 1.0
    heights = counts.astype("float32")
    colors, lo, hi = _bar_colors(heights, cmap, crange)
    return BarData(centers, heights, colors, "count", col, None, False,
                   width, (lo, hi), (lo, hi), len(heights))


def _short_part(s: str) -> str:
    """``Part(12)`` → ``P12`` for compact bar labels; other labels untouched."""
    return "P" + s[5:-1] if s.startswith("Part(") and s.endswith(")") else s


def build_cov(df, spec, *, cmap=None, scale="linear", crange=None) -> BarData:
    """One bar per group of a signal's coefficient of variation.

    Reduction mode (``overall`` / ``per_layer_mean`` / ``across_layers``) comes
    from ``spec.cov_mode``; the CoV itself is computed by ``ohpal.ampm.stats``.
    """
    import polars as pl

    from ohpal.ampm.stats import compute_cov

    cmap = cmap or DEFAULT_COLORMAP
    grp = spec.group_by or spec.x
    sig = spec.y
    for c in (grp, sig):
        if not c or c not in df.columns:
            raise KeyError(f"Column {c!r} is not in the data.")

    work = df.filter(pl.col(grp).is_not_null())
    cov_df = compute_cov(
        work, [sig], group_by=grp, mode=(spec.cov_mode or "overall"),
        drop_noise=True, noise_label="noise",
    )
    cov_col = f"cov_{sig}"
    cov_df = cov_df.filter(pl.col(cov_col).is_not_null()).sort(grp)
    value_name = f"CoV · {sig}"
    if cov_df.height == 0:
        empty = np.zeros((0, 4), "float32")
        return BarData(np.zeros(0, "float32"), np.zeros(0, "float32"), empty,
                       value_name, grp, None, True, 0.8, None, None, 0)
    labels = [_short_part(str(v)) for v in cov_df[grp].to_list()]
    heights = cov_df[cov_col].to_numpy().astype("float32")
    labels, heights = _sort_bars(labels, heights, spec.sort)
    colors, lo, hi = _bar_colors(heights, cmap, crange)
    n = len(labels)
    return BarData(np.arange(n, dtype="float32"), heights, colors,
                   value_name, grp, labels, True, 0.8, (lo, hi), (lo, hi), n)


# -- distributions: KDE curves, violins; the k-distance curve -------------
KDE_POINTS = 512          # evaluation points per KDE curve
KDIST_SAMPLE = 50_000     # points the k-distance curve is computed on
MAX_VIOLINS = 60          # more categories than this is unreadable


def kde_bandwidth(values: np.ndarray, method: str | None = "scott") -> float:
    """The Gaussian kernel's standard deviation, by Scott's or Silverman's
    rule: the same choices (and values) as ``scipy.stats.gaussian_kde``."""
    n = values.size
    sd = float(np.std(values, ddof=1)) if n > 1 else 0.0
    factor = (n * 0.75) ** -0.2 if method == "silverman" else n ** -0.2
    return sd * factor


def kde_density(values: np.ndarray, grid: np.ndarray, bw: float) -> np.ndarray:
    """Gaussian KDE of ``values`` on the evenly spaced ``grid``.

    Linear binning onto the grid, then one convolution with the kernel:
    every point is used (no sampling) and it stays fast on millions of rows.
    The result matches a direct ``gaussian_kde`` evaluation to well within
    what is visible on a plot."""
    m = grid.size
    if values.size == 0 or m < 2 or not np.isfinite(bw) or bw <= 0:
        return np.zeros(m, "float64")
    dx = float(grid[1] - grid[0])
    pos = np.clip((values - grid[0]) / dx, 0.0, m - 1.0)
    i = np.minimum(np.floor(pos).astype(np.int64), m - 2)
    frac = pos - i
    counts = (np.bincount(i, weights=1.0 - frac, minlength=m)
              + np.bincount(i + 1, weights=frac, minlength=m))[:m]
    half = int(np.ceil(4.0 * bw / dx))
    offsets = np.arange(-half, half + 1) * dx
    kernel = np.exp(-0.5 * (offsets / bw) ** 2)
    kernel /= kernel.sum()
    # A direct convolution (the grid is a few hundred points), centred as
    # "same" mode; numpy only, so no SciPy signal import (half a second).
    full = np.convolve(counts, kernel)
    start = (kernel.size - 1) // 2
    density = full[start:start + m] / (values.size * dx)
    return np.clip(density, 0.0, None)


def _category_codes(s, uniques: list) -> np.ndarray:
    """Each value's index in ``uniques`` (nulls: None's index, else 0)."""
    import polars as pl

    code_of = {v: i for i, v in enumerate(uniques)}
    missing = code_of.get(None, 0)
    non_null = [v for v in uniques if v is not None]
    try:
        if not non_null:
            return np.full(len(s), missing, dtype=int)
        old = pl.Series(non_null, dtype=s.dtype)
        new = pl.Series([code_of[v] for v in non_null], dtype=pl.Int64)
        return (s.replace_strict(old, new, default=missing).fill_null(missing)
                .to_numpy().astype(int))
    except Exception:  # noqa: BLE001 - an unusual dtype: value by value
        return np.array([code_of.get(v, 0) for v in s.to_list()], dtype=int)


def _finite(series) -> np.ndarray:
    v = series.to_numpy().astype("float64", copy=False)
    return v[np.isfinite(v)]


def _require(df, *names) -> None:
    for c in names:
        if c and c not in df.columns:
            raise KeyError(f"Column {c!r} is not in the data.")


def _sample_colors(n: int, cmap: str | None) -> np.ndarray:
    """``n`` distinct colours spread along a colormap (one per group)."""
    t = (np.array([0.5], "float32") if n <= 1
         else np.linspace(0.0, 1.0, n, dtype="float32"))
    return _apply_cmap(t, cmap or DEFAULT_COLORMAP).astype("float32")


@dataclass
class CurveData:
    """One or more curves over a shared x: KDE densities, the k-distance curve."""

    x: np.ndarray                 # (M,) shared x of every curve
    ys: list                      # one (M,) array per curve
    names: list                   # one label per curve
    counts: list                  # rows behind each curve
    colors: np.ndarray            # (n, 4) one colour per curve
    x_name: str
    y_name: str
    group_name: str | None = None   # the column the curves are split by
    knee: tuple | None = None       # k-distance: the knee point (x, y), if any
    skipped: int = 0                # groups with too few values to draw
    n: int = 0
    slopes: list | None = None      # k-distance: dy/dx per point, per curve


# The k-distance curve's slope at a point is taken over this share of the
# points on each side of it: the sorted distances step, so the slope from one
# point to the next is mostly 0 or a spike.
KDIST_SLOPE_SPAN = 0.005


def curve_slope(x, y, span: float = KDIST_SLOPE_SPAN) -> np.ndarray:
    """dy/dx at every point of a curve, from the points ``span`` of the curve
    to each side (fewer at the ends)."""
    x = np.asarray(x, "float64")
    y = np.asarray(y, "float64")
    n = y.size
    if n < 2:
        return np.zeros(n)
    w = max(1, round(n * span))
    i = np.arange(n)
    lo, hi = np.maximum(i - w, 0), np.minimum(i + w, n - 1)
    return (y[hi] - y[lo]) / (x[hi] - x[lo])


def kdist_eps(distance: float, spec) -> tuple[float, float | None]:
    """The DBSCAN radii a k-distance stands for: (eps XY, eps Z), eps Z None
    in 2D. In 3D, Z is stretched by eps_xy / eps_z before distances are
    measured, so a distance d on the curve is DBSCAN's reach with eps XY = d
    and eps Z = d * eps_z / eps_xy (the ratio the plot was made with)."""
    d = float(distance)
    if not spec.z:
        return d, None
    return d, d * float(spec.eps_z or 1.0) / float(spec.eps_xy or 1.0)


def eps_text(eps_xy: float, eps_z: float | None, approx: bool = False) -> str:
    """The radii as text: eps XY 0.164 mm, Z 0.0329 mm (only XY in 2D)."""
    sep = " \u2248 " if approx else " "
    text = f"eps XY{sep}{eps_xy:.4g} mm"
    if eps_z is not None:
        text += f", Z{sep}{eps_z:.4g} mm"
    return text


def knee_index(y) -> int | None:
    """The knee of a rising, bending-up curve (the sorted k-distances): the
    Kneedle method (Satopaa et al., 2011). With both axes scaled to 0..1, the
    knee is the point furthest below the straight line from the first point to
    the last. None when the curve doesn't rise."""
    y = np.asarray(y, "float64")
    if y.size < 3 or not y[-1] > y[0]:
        return None
    x = np.linspace(0.0, 1.0, y.size)
    i = int(np.argmax(x - (y - y[0]) / (y[-1] - y[0])))
    return i if 0 < i < y.size - 1 else None


def build_kde(df, spec, *, cmap=None, scale="linear", crange=None) -> CurveData:
    """Overlaid kernel-density curves of ``spec.x``, one per value of
    ``spec.group_by`` (or a single curve), as the old Plotly KDE view drew them:
    Scott's (or Silverman's) bandwidth, a shared x grid over the data range
    padded 5%, "noise" and empty groups dropped."""
    import polars as pl

    col, grp = spec.x, spec.group_by
    _require(df, col, grp)
    work = df.select([c for c in (col, grp) if c])
    if grp:
        work = work.filter(pl.col(grp).is_not_null()
                           & (pl.col(grp).cast(pl.Utf8) != "noise"))
    allv = _finite(work[col])
    if allv.size < 2:
        raise ValueError(f"Not enough values in {col!r} to estimate a density.")
    lo, hi = float(allv.min()), float(allv.max())
    if hi <= lo:
        raise ValueError(f"Every value of {col!r} is the same ({_short(lo)}), "
                         "so there is no distribution to draw.")
    pad = 0.05 * (hi - lo)
    grid = np.linspace(lo - pad, hi + pad, KDE_POINTS)

    if grp:
        parts = (work.group_by(grp, maintain_order=True)
                 .agg(pl.col(col)).sort(grp))
        # One flat array split per group (not a Python list per value).
        flat = parts[col].explode().cast(pl.Float64).to_numpy()
        ends = np.cumsum(parts[col].list.len().to_numpy())
        groups = [(str(k), v) for k, v in
                  zip(parts[grp].to_list(), np.split(flat, ends[:-1]))]
    else:
        groups = [(col, allv)]

    names, ys, counts, skipped = [], [], [], 0
    for name, vals in groups:
        vals = vals[np.isfinite(vals)]
        bw = kde_bandwidth(vals, spec.bandwidth) if vals.size > 1 else 0.0
        if vals.size < 2 or bw <= 0:
            skipped += 1
            continue
        names.append(name)
        ys.append(kde_density(vals, grid, bw))
        counts.append(int(vals.size))
    if not ys:
        raise ValueError("No group has enough distinct values for a density curve.")
    return CurveData(grid, ys, names, counts, _sample_colors(len(ys), cmap),
                     col, "Density", grp, None, skipped, len(ys))


def build_kdist(df, spec, *, cmap=None, scale="linear", crange=None) -> CurveData:
    """The sorted k-distance curve that DBSCAN's eps is read from: for each
    point, the distance to its k-th nearest neighbour (Z scaled by
    eps_xy / eps_z in 3D, as DBSCAN measures it), sorted. Its knee
    (``knee_index``) suggests eps; its slope at every point is kept for the
    hover.

    Unlike ``ohpal.ampm.clustering.k_distance_curve``, which samples 50,000
    points and searches only among them, the neighbours here are searched
    among *every* point; only the points reported are sampled. The app's
    DBSCAN (``cluster_dbscan_chunked``) clusters at full density, and a
    sparser sample would overstate its neighbour distances several-fold."""
    from scipy.spatial import cKDTree

    cols = [c for c in (spec.x, spec.y, spec.z) if c]
    _require(df, *cols)
    k = max(1, int(spec.k or 10))
    coords = df.select(cols).drop_nulls().to_numpy().astype("float64")
    coords = coords[np.isfinite(coords).all(axis=1)]
    if coords.shape[0] <= k:
        raise ValueError(f"Need more than {k} points for a {k}-distance curve.")
    eps_xy = float(spec.eps_xy or 1.0)
    if spec.z:
        eps_z = float(spec.eps_z or 1.0)
        if eps_z <= 0:
            raise ValueError("The Z radius must be greater than zero.")
        coords[:, 2] *= eps_xy / eps_z
    tree = cKDTree(coords)
    probe = coords
    if coords.shape[0] > KDIST_SAMPLE:
        pick = np.random.default_rng(0).choice(
            coords.shape[0], KDIST_SAMPLE, replace=False)
        probe = coords[pick]
    dist, _ = tree.query(probe, k=k + 1, workers=-1)
    kth = np.sort(dist[:, k])
    rank = np.arange(kth.size, dtype="float64")
    i = knee_index(kth)
    knee = None if i is None else (float(rank[i]), float(kth[i]))
    return CurveData(rank, [kth], [f"{k}-distance"], [int(kth.size)],
                     _sample_colors(1, "turbo"), "Rank (points, sorted)",
                     f"{k}-distance (mm)", None, knee, 0, 1,
                     [curve_slope(rank, kth)])


@dataclass
class ViolinData:
    centers: np.ndarray           # (n,) x of each violin
    labels: list                  # category label under each
    outlines: list                # per violin: (y values, half widths)
    stats: list                   # per violin: dict n, min, q1, median, q3, max
    colors: np.ndarray            # (n, 4) coloured by median
    x_name: str
    value_name: str
    crange: tuple | None = None
    full_range: tuple | None = None
    n: int = 0


def build_violins(df, spec, *, cmap=None, scale="linear", crange=None) -> ViolinData:
    """One violin of ``spec.y`` per category of ``spec.x``: its KDE mirrored,
    over the category's own range, every violin the same maximum width.
    Coloured by the median, like bars are by their height."""
    import polars as pl

    cat, val = spec.x, spec.y
    _require(df, cat, val)
    work = (df.select([cat, val])
            .filter(pl.col(cat).is_not_null() & pl.col(val).is_not_null()))
    parts = work.group_by(cat, maintain_order=True).agg(pl.col(val)).sort(cat)
    if parts.height > MAX_VIOLINS:
        raise ValueError(
            f"{cat!r} has {parts.height} different values; a violin plot needs "
            f"{MAX_VIOLINS} or fewer. Choose a grouping column such as part_id.")
    labels, outlines, stats = [], [], []
    flat = parts[val].explode().cast(pl.Float64).to_numpy()
    ends = np.cumsum(parts[val].list.len().to_numpy())
    for key, v in zip(parts[cat].to_list(), np.split(flat, ends[:-1])):
        v = v[np.isfinite(v)]
        if v.size == 0:
            continue
        q1, med, q3 = (float(q) for q in np.percentile(v, [25, 50, 75]))
        lo, hi = float(v.min()), float(v.max())
        if hi > lo and v.size > 1:
            grid = np.linspace(lo, hi, 200)
            dens = kde_density(v, grid, kde_bandwidth(v, spec.bandwidth))
            peak = float(dens.max()) or 1.0
            half = 0.4 * dens / peak
        else:  # one value: a flat line, not a shape
            grid, half = np.array([lo, hi]), np.array([0.4, 0.4])
        labels.append(_short_part(str(key)))
        outlines.append((grid.astype("float32"), half.astype("float32")))
        stats.append({"n": int(v.size), "min": lo, "q1": q1, "median": med,
                      "q3": q3, "max": hi, "key": str(key)})
    n = len(labels)
    medians = np.array([st["median"] for st in stats], dtype="float64")
    colors, clo, chi = _bar_colors(medians, cmap or DEFAULT_COLORMAP, crange)
    full = (float(medians.min()), float(medians.max())) if n else None
    return ViolinData(np.arange(n, dtype="float32"), labels, outlines, stats,
                      colors, cat, val, (clo, chi), full, n)


def _short(v: float) -> str:
    return f"{v:.6g}"


@dataclass
class ContourData:
    z: np.ndarray          # (ny, nx) float32, NaN for empty grid cells
    x_values: np.ndarray   # (nx,) sorted unique x (grid column coords)
    y_values: np.ndarray   # (ny,) sorted unique y (grid row coords)
    points: np.ndarray     # (M, 2) measured (x, y) for the overlay
    value_name: str        # colourbar label (the z column)
    x_name: str
    y_name: str
    crange: tuple
    full_range: tuple
    n: int                 # number of filled cells
    show_points: bool = True
    # The smooth surface that is drawn: z interpolated between the measured
    # points on a fine regular grid spanning ``extent``; NaN where there is
    # nothing to interpolate from (outside the measured region).
    field: np.ndarray = None           # (CONTOUR_RES, CONTOUR_RES) float32
    extent: tuple = (0.0, 1.0, 0.0, 1.0)  # (xmin, xmax, ymin, ymax)


CONTOUR_RES = 400      # samples per axis of the interpolated field
# A contour is drawn over a parameter grid: a handful of distinct x and y
# values. An axis with more distinct values than this is continuous data, so
# its values are put into CONTOUR_STEPS equal steps first (a million distinct
# values would otherwise make a million-column grid).
CONTOUR_MAX_STEPS = 400
CONTOUR_STEPS = 200
CONTOUR_BANDS = 16     # filled bands aimed for (the step is rounded to be nice)


def nice_levels(lo: float, hi: float, target: int = CONTOUR_BANDS) -> np.ndarray:
    """Band edges covering [lo, hi] on a round step (1, 2, 3 or 5 x 10^k), at
    most ``target`` bands of them: what a filled-contour plot calls levels."""
    lo, hi = float(lo), float(hi)
    if not (np.isfinite(lo) and np.isfinite(hi)) or hi <= lo:
        return np.array([lo, lo + 1.0], dtype="float64")
    raw = (hi - lo) / max(1, int(target))
    mag = 10.0 ** np.floor(np.log10(raw))
    step = next((m * mag for m in (1.0, 2.0, 3.0, 5.0, 10.0)
                 if m * mag >= raw * 0.999), 10.0 * mag)
    first = np.floor(lo / step + 1e-9) * step
    count = int(np.ceil((hi - first) / step - 1e-9))
    levels = first + step * np.arange(count + 1)
    return np.round(levels, 12)


def level_labels(levels: np.ndarray, most: int = 9) -> list[tuple[int, str]]:
    """Which levels to label along a banded colour bar, and how: every level,
    or every 2nd, 3rd… counted from the bottom, so that at most ``most`` are
    labelled. All share the decimals the step needs. Returns (index, text)."""
    n = len(levels) - 1
    if n < 1:
        return []
    every = max(1, int(np.ceil((n + 1) / most)))
    step = abs(float(levels[1] - levels[0]))
    places = max(0, int(-np.floor(np.log10(step) + 1e-9))) if 0 < step < 1 else 0
    return [(i, f"{float(levels[i]):.{places}f}") for i in range(0, n + 1, every)]


def band_colors(levels: np.ndarray, cmap: str | None) -> np.ndarray:
    """One rgba colour per band (``len(levels) - 1`` of them), spread evenly
    over the colormap from its first colour to its last."""
    n = max(1, len(levels) - 1)
    t = np.array([0.5], "float32") if n == 1 else np.linspace(0, 1, n, dtype="float32")
    return _apply_cmap(t, cmap or DEFAULT_COLORMAP).astype("float32")


def band_image(field: np.ndarray, levels: np.ndarray, cmap: str | None) -> np.ndarray:
    """The field as filled bands: every sample takes the colour of the band
    its value falls in (values past the ends take the end bands); NaN is clear."""
    colors = band_colors(levels, cmap)
    finite = np.isfinite(field)
    idx = np.digitize(np.where(finite, field, levels[0]), levels[1:-1])
    rgba = colors[np.clip(idx, 0, len(colors) - 1)]
    rgba[~finite] = 0.0
    return rgba.astype("float32")


def _nearest(sorted_values: np.ndarray, q: np.ndarray) -> np.ndarray:
    """For each of ``q``, the index of the nearest of ``sorted_values``."""
    if len(sorted_values) < 2:
        return np.zeros(len(q), dtype=np.intp)
    i = np.clip(np.searchsorted(sorted_values, q), 1, len(sorted_values) - 1)
    left, right = sorted_values[i - 1], sorted_values[i]
    return np.where(q - left <= right - q, i - 1, i)


def _steps(col: str, sub):
    """``col`` put into CONTOUR_STEPS equal steps (each value replaced by its
    step's middle) when it has too many distinct values for a grid."""
    import polars as pl

    if sub[col].n_unique() <= CONTOUR_MAX_STEPS:
        return pl.col(col)
    lo, hi = float(sub[col].min()), float(sub[col].max())
    width = (hi - lo) / CONTOUR_STEPS
    k = ((pl.col(col).cast(pl.Float64) - lo) / width).floor().clip(0, CONTOUR_STEPS - 1)
    return (lo + (k + 0.5) * width).alias(col)


def _interpolate(xs, ys, grid, px, py, pz, fx, fy) -> np.ndarray:
    """z over the fine grid (``fx`` x ``fy``) from the measured points.

    A complete rectangular set of measurements gets a smooth spline surface
    through every point; an incomplete one is interpolated between whichever
    points exist (cubic where possible) and left NaN outside them. The result
    is kept within the measured range, so the picture never shows a value
    beyond anything that was measured.
    """
    out = None
    try:
        if np.isfinite(grid).all() and len(xs) >= 2 and len(ys) >= 2:
            from scipy.interpolate import RectBivariateSpline

            spline = RectBivariateSpline(
                ys, xs, grid.astype("float64"),
                kx=min(3, len(ys) - 1), ky=min(3, len(xs) - 1))
            out = spline(fy, fx)
        elif len(pz) >= 3:
            from scipy.interpolate import griddata

            gx, gy = np.meshgrid(fx, fy)
            pts = np.column_stack([px, py])
            for method in ("cubic", "linear"):
                try:
                    out = griddata(pts, pz, (gx, gy), method=method, rescale=True)
                    break
                except Exception:  # noqa: BLE001 - e.g. too few / collinear points
                    out = None
    except Exception:  # noqa: BLE001 - SciPy missing or a degenerate layout
        out = None
    if out is None:
        # Fallback: each fine sample takes its nearest measured cell.
        out = grid[np.ix_(_nearest(ys, fy), _nearest(xs, fx))].astype("float64")
    if len(pz):
        out = np.clip(out, float(np.min(pz)), float(np.max(pz)))  # NaN stays NaN
    return out.astype("float32")


def build_contour(df, spec, *, cmap=None, scale="linear", crange=None) -> ContourData:
    """``spec.z`` as a smooth surface over the (``spec.x``, ``spec.y``) plane.

    Long-form in: rows carrying a measured (x, y) and its z. Rows sharing an
    (x, y) are averaged. ``z`` keeps the coarse measured grid (each unique x a
    column, each unique y a row, NaN where nothing was measured); ``field`` is
    the interpolated surface the plot draws as filled bands.
    """
    import polars as pl

    x, y, z = spec.x, spec.y, spec.z
    for c in (x, y, z):
        if not c or c not in df.columns:
            raise KeyError(f"Column {c!r} is not in the data.")
    if not (df[x].dtype.is_numeric() and df[y].dtype.is_numeric()):
        raise ValueError("Contour needs numeric X and Y columns.")

    keep = pl.col(x).is_not_null() & pl.col(y).is_not_null() & pl.col(z).is_not_null()
    sub = df.select([x, y, z]).filter(keep)
    if sub.height == 0:
        empty = np.zeros((0, 0), "float32")
        return ContourData(empty, np.zeros(0, "float32"), np.zeros(0, "float32"),
                           np.zeros((0, 2), "float32"), z, x, y, (0.0, 1.0),
                           (0.0, 1.0), 0, spec.show_points, empty)

    sub = sub.with_columns(_steps(x, sub), _steps(y, sub))
    xs = np.sort(sub[x].unique().to_numpy().astype("float64"))
    ys = np.sort(sub[y].unique().to_numpy().astype("float64"))
    grid = np.full((len(ys), len(xs)), np.nan, dtype="float32")
    g = (sub.group_by([y, x], maintain_order=True)
         .agg(pl.col(z).cast(pl.Float64).mean().alias("_v"))
         .filter(pl.col("_v").is_finite()))
    if g.height:
        grid[np.searchsorted(ys, g[y].to_numpy().astype("float64")),
             np.searchsorted(xs, g[x].to_numpy().astype("float64"))] = g["_v"].to_numpy()

    finite = np.isfinite(grid)
    if crange is not None:
        lo, hi = float(crange[0]), float(crange[1])
    elif finite.any():
        lo, hi = float(np.nanmin(grid)), float(np.nanmax(grid))
    else:
        lo, hi = 0.0, 1.0
    # One overlay marker per measured combination (not per row).
    px = g[x].to_numpy().astype("float64")
    py = g[y].to_numpy().astype("float64")
    pz = g["_v"].to_numpy().astype("float64")
    pts = np.column_stack([px, py]).astype("float32")
    extent = (float(xs[0]), float(xs[-1]), float(ys[0]), float(ys[-1]))
    fx = np.linspace(extent[0], extent[1], CONTOUR_RES)
    fy = np.linspace(extent[2], extent[3], CONTOUR_RES)
    field = _interpolate(xs, ys, grid, px, py, pz, fx, fy)
    return ContourData(grid, xs.astype("float32"), ys.astype("float32"), pts,
                       z, x, y, (lo, hi), (lo, hi), int(finite.sum()),
                       spec.show_points, field, extent)


def _apply_cmap(t: np.ndarray, name: str) -> np.ndarray:
    """Map t in [0,1] to rgba via the named colormap's stops."""
    lut = _LUTS.get(name, _LUTS[DEFAULT_COLORMAP])
    t = np.clip(t, 0.0, 1.0)
    pos = t * (len(lut) - 1)
    lo = np.floor(pos).astype(int)
    hi = np.minimum(lo + 1, len(lut) - 1)
    frac = (pos - lo).reshape(-1, 1)
    rgb = lut[lo] * (1 - frac) + lut[hi] * frac
    out = np.ones((len(t), 4), dtype="float32")
    out[:, :3] = rgb
    return out


def _axis_array(df, name: str) -> np.ndarray:
    s = df[name]
    if s.dtype.is_numeric():
        return s.to_numpy().astype("float32")
    # Non-numeric axis: factorise to stable integer codes.
    import polars as pl

    return s.cast(pl.Categorical).to_physical().to_numpy().astype("float32")


def build(df, spec, max_points: int = 150_000, seed: int = 0, *,
          cmap: str = DEFAULT_COLORMAP, scale: str = "linear",
          crange: tuple | None = None) -> RenderData:
    import polars as pl

    cols = df.columns
    for ch in [*spec.axes, spec.color]:
        if ch and ch not in cols:
            raise KeyError(f"Column {ch!r} is not in the data.")

    # Drop rows null (or non-finite, for floats) on any axis.
    keep = pl.lit(True)
    for a in spec.axes:
        cond = pl.col(a).is_not_null()
        if df[a].dtype.is_float():
            cond = cond & pl.col(a).is_finite()
        keep = keep & cond
    sub = df.filter(keep)
    n_total = sub.height

    if n_total == 0:
        empty = np.zeros((0, 3 if spec.is_3d else 2), dtype="float32")
        return RenderData(empty, np.zeros((0, 4), "float32"), spec.is_3d,
                          tuple(spec.axes), None, 0, 0)

    # Decimate indices once, shared across all channels.
    idx = None
    if n_total > max_points:
        rng = np.random.default_rng(seed)
        idx = np.sort(rng.choice(n_total, max_points, replace=False))

    def take(arr):
        return arr if idx is None else arr[idx]

    pos_cols = [take(_axis_array(sub, a)) for a in spec.axes]
    pos = np.column_stack(pos_cols).astype("float32")

    colors, legend, eff_range, full_range = _colors(
        sub, spec, idx, take, len(pos), cmap, scale, crange)
    drawn = sub if idx is None else sub[idx]  # rows actually plotted, for hover
    return RenderData(pos, colors, spec.is_3d, tuple(spec.axes), legend,
                      n_total, len(pos), eff_range, full_range, rows=drawn)


# -- Mean ± SD: one point per group, with error bars -------------------
# Two-sided 95% t quantiles for 1..30 degrees of freedom (beyond: 1.96).
_T95 = (12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228,
        2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086,
        2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042)
# Column names of the group table (``RenderData.rows`` of a mean-sd plot).
MS_GROUP, MS_X, MS_MEAN, MS_SD, MS_N, MS_ERR = (
    "__group", "__x", "__mean", "__sd", "__n", "__err")


def t95(dof: int) -> float:
    """The two-sided 95% Student's t quantile for ``dof`` degrees of freedom."""
    if dof < 1:
        return float("nan")
    try:
        from scipy.stats import t as student

        return float(student.ppf(0.975, dof))
    except Exception:  # noqa: BLE001 - no SciPy: the table
        return _T95[dof - 1] if dof <= len(_T95) else 1.96


def error_half(sd, n, kind: str):
    """Error bar half-heights from the sample SDs and counts: ``sd``, ``se``
    (SD / sqrt(n)), ``ci95`` (t(n-1) x SE) or ``none``. NaN where n < 2."""
    sd = np.asarray(sd, dtype="float64")
    n = np.asarray(n, dtype="float64")
    ok = n >= 2
    out = np.full(sd.shape, np.nan)
    if kind == "sd":
        out[ok] = sd[ok]
    elif kind == "se":
        out[ok] = sd[ok] / np.sqrt(n[ok])
    elif kind == "ci95":
        t = np.array([t95(int(k) - 1) for k in n[ok]])
        out[ok] = t * sd[ok] / np.sqrt(n[ok])
    return out


def value_label(columns) -> str:
    """The y axis's name for several value columns: what they share
    (``Density (1)``, ``Density (2)`` -> ``Density``), else them all."""
    from .plotspec import repeat_base

    cols = list(columns)
    if len(cols) == 1:
        return cols[0]
    bases = {repeat_base(c) for c in cols}
    if len(bases) == 1:
        return next(iter(bases))
    return ", ".join(cols)


def build_meansd(df, spec, *, sample: str | None = None,
                 cmap: str = DEFAULT_COLORMAP, scale: str = "linear",
                 crange: tuple | None = None) -> RenderData:
    """One point per ``spec.group_by`` group: the mean of its values, with an
    error bar (``spec.error``).

    The table has a row per measured point, so a per-part value (a density
    from the samples template) is on thousands of rows. Each *sample* (a
    ``sample`` value, the part, when that column is given and isn't the group)
    counts once: its value in each value column is the mean of its rows (for a
    per-part column, just its value). The group's values are then every
    sample's value in every value column (``spec.values``): the mean, the
    sample SD (n - 1) and n are over those. X is the mean of the samples' X.
    Points in no sample (no part, or DBSCAN's "noise") are left out.
    A colour column is the group's mean (numbers) or first value (text)."""
    import polars as pl

    values = spec.values
    group = spec.group_by
    if not group:
        raise ValueError("Choose a column to group by (one point per group).")
    for ch in [spec.x, group, *values, spec.color]:
        if ch and ch not in df.columns:
            raise KeyError(f"Column {ch!r} is not in the data.")
    for c in [spec.x, *values]:
        if not df[c].dtype.is_numeric():
            raise ValueError(f"{c!r} isn't a numeric column.")

    keys = [group]
    if sample and sample != group and sample in df.columns:
        keys.append(sample)
    keep = pl.col(group).is_not_null()
    if sample and sample in df.columns:
        # Points in no part (null) or DBSCAN's "noise" are no sample.
        keep = keep & pl.col(sample).is_not_null()
        if not df[sample].dtype.is_numeric():
            keep = keep & (pl.col(sample).cast(pl.Utf8) != "noise")
    color = spec.color
    by_color = bool(color) and color != group  # else: none, or the group itself
    sub = df.filter(keep).select(
        *keys, pl.col(spec.x).cast(pl.Float64).alias("__x0"),
        *[pl.col(c).cast(pl.Float64).alias(f"__r{i}") for i, c in enumerate(values)],
        *([pl.col(color).alias("__c0")] if by_color else []))

    def finite_mean(c):
        col = pl.col(c)
        return col.filter(col.is_finite()).mean()

    def reduce(c, numeric):
        return pl.col(c).mean() if numeric else pl.col(c).drop_nulls().first()

    color_numeric = bool(color) and df[color].dtype.is_numeric()
    per_sample = sub.group_by(keys).agg(
        finite_mean("__x0").alias(MS_X),
        *[finite_mean(f"__r{i}").alias(f"__v{i}") for i in range(len(values))],
        *([reduce("__c0", color_numeric).alias("__c")] if by_color else []),
    )
    vcols = [f"__v{i}" for i in range(len(values))]
    long = per_sample.unpivot(index=[group], on=vcols, value_name="__val")
    stats = long.filter(pl.col("__val").is_not_null()).group_by(group).agg(
        pl.col("__val").mean().alias(MS_MEAN),
        pl.col("__val").std(ddof=1).alias(MS_SD),
        pl.col("__val").count().alias(MS_N),
    )
    first = [pl.col(MS_X).mean().alias(MS_X)]
    if by_color:
        first.append(reduce("__c", color_numeric).alias(color))
    groups = (per_sample.group_by(group).agg(*first)
              .join(stats, on=group, how="inner")
              .filter(pl.col(MS_X).is_not_null() & pl.col(MS_X).is_finite()
                      & pl.col(MS_MEAN).is_not_null()))
    order = sorted(range(groups.height), key=lambda i: (
        _natural_key(groups[group][i])))
    groups = groups[order] if order else groups
    groups = groups.with_columns(pl.col(group).alias(MS_GROUP))

    n = groups.height
    if n == 0:
        empty = np.zeros((0, 2), dtype="float32")
        return RenderData(empty, np.zeros((0, 4), "float32"), False,
                          (spec.x, value_label(values)), None, 0, 0)
    sd = groups[MS_SD].fill_null(np.nan).to_numpy().astype("float64")
    counts = groups[MS_N].to_numpy()
    err = error_half(sd, counts, spec.error)
    groups = groups.with_columns(pl.Series(MS_ERR, err))
    pos = np.column_stack([groups[MS_X].to_numpy(),
                           groups[MS_MEAN].to_numpy()]).astype("float32")
    colors, legend, eff_range, full_range = _colors(
        groups, spec, None, lambda a: a, n, cmap, scale, crange)
    return RenderData(pos, colors, False, (spec.x, value_label(values)), legend,
                      n, n, eff_range, full_range, rows=groups,
                      err=err.astype("float32"))


def _colors(sub, spec, idx, take, n, cmap, scale, crange):
    if not spec.color:
        colors = np.tile(np.array(_SOLID, dtype="float32"), (n, 1))
        return colors, None, None, None

    s = sub[spec.color]
    if s.dtype.is_numeric():
        vals = take(s.to_numpy().astype("float32"))
        # Full extent in original units (before any log transform) — what the
        # Min/Max sliders map their 0–100% against.
        raw_ok = np.isfinite(vals)
        full_range = (
            (float(np.min(vals[raw_ok])), float(np.max(vals[raw_ok])))
            if raw_ok.any() else None
        )
        if scale == "log":  # map on log10 of positive values
            vals = np.where(vals > 0, np.log10(np.maximum(vals, 1e-12)), np.nan)
        finite = np.isfinite(vals)
        if crange is not None:
            lo, hi = float(crange[0]), float(crange[1])
            if scale == "log":
                lo = np.log10(lo) if lo > 0 else (np.min(vals[finite]) if finite.any() else 0.0)
                hi = np.log10(hi) if hi > 0 else (np.max(vals[finite]) if finite.any() else 1.0)
        elif finite.any():
            # Robust auto-range: clip to the 2nd–98th percentile so a few
            # outliers don't stretch the scale and wash the bulk into one
            # colour. Sliders can widen back to the full extent.
            lo = float(np.percentile(vals[finite], 2.0))
            hi = float(np.percentile(vals[finite], 98.0))
            if hi <= lo:  # flat / too few distinct values → full extent
                lo = float(np.min(vals[finite]))
                hi = float(np.max(vals[finite]))
        else:
            lo, hi = 0.0, 1.0
        span = (hi - lo) or 1.0
        t = np.where(finite, (vals - lo) / span, 0.0)
        colors = _apply_cmap(t, cmap)
        colors[:, 3] = 1.0  # opaque fill (no washed-out look on a light bg)
        colors[~finite] = _NULL_RGBA  # nulls shown neutral + faded, not dropped
        # Report the effective range in the original (non-log) units for sliders.
        rng = crange if crange is not None else (
            (10 ** lo, 10 ** hi) if scale == "log" else (lo, hi)
        )
        return (colors, ("colorbar", rng[0], rng[1], spec.color),
                (rng[0], rng[1]), full_range)

    # Categorical: one colour per category, with a legend of the categories.
    # Categories are sorted, so a category keeps its colour whatever rows (or
    # layer) are on screen. Up to 8 take the colour-blind-safe palette; more
    # are spread along the colormap so every one is distinct.
    uniques = sorted(s.unique().to_list(),
                     key=lambda v: (v is None, _natural_key(v)))
    codes = _category_codes(s, uniques)
    codes = codes if idx is None else codes[idx]
    if len(uniques) <= len(_CATEGORICAL):
        pal = np.column_stack([_CATEGORICAL[:max(1, len(uniques))],
                               np.ones(max(1, len(uniques)), "float32")])
    else:
        pal = _sample_colors(len(uniques), cmap)
        pal[:, 3] = 1.0
    colors = pal[codes].astype("float32")
    legend = [(str(v), tuple(float(c) for c in pal[i])) for i, v in enumerate(uniques)]
    return colors, legend, None, None
