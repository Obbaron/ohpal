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
    colors, lo, hi = _bar_colors(heights, cmap, crange)
    n = len(labels)
    return BarData(np.arange(n, dtype="float32"), heights, colors, val, cat,
                   labels, True, 0.8, (lo, hi), (lo, hi), n)


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
    colors, lo, hi = _bar_colors(heights, cmap, crange)
    n = len(labels)
    return BarData(np.arange(n, dtype="float32"), heights, colors,
                   value_name, grp, labels, True, 0.8, (lo, hi), (lo, hi), n)


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
        ix = np.abs(fx[:, None] - xs[None, :]).argmin(axis=1)
        iy = np.abs(fy[:, None] - ys[None, :]).argmin(axis=1)
        out = grid[np.ix_(iy, ix)].astype("float64")
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

    xs = np.sort(sub[x].unique().to_numpy().astype("float64"))
    ys = np.sort(sub[y].unique().to_numpy().astype("float64"))
    xi = {float(v): i for i, v in enumerate(xs)}
    yi = {float(v): i for i, v in enumerate(ys)}
    grid = np.full((len(ys), len(xs)), np.nan, dtype="float32")
    g = (sub.group_by([y, x], maintain_order=True)
         .agg(pl.col(z).cast(pl.Float64).mean().alias("_v"))
         .filter(pl.col("_v").is_finite()))
    for row in g.iter_rows(named=True):
        grid[yi[float(row[y])], xi[float(row[x])]] = row["_v"]

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

    # Categorical: stable codes -> palette, with a legend of the categories.
    import polars as pl

    uniques = s.unique(maintain_order=True).to_list()
    code_of = {v: i for i, v in enumerate(uniques)}
    codes_full = s.to_list()
    codes = np.array([code_of.get(v, 0) for v in codes_full], dtype=int)
    codes = codes if idx is None else codes[idx]
    pal = _CATEGORICAL
    colors = np.ones((len(codes), 4), dtype="float32")
    colors[:, :3] = pal[codes % len(pal)]
    colors[:, 3] = 1.0
    legend = [
        (str(v), tuple(pal[i % len(pal)]) + (1.0,))
        for i, v in enumerate(uniques)
    ]
    return colors, legend, None, None
