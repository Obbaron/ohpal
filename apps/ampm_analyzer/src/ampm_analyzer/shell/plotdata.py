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

# 8-stop viridis approximation (RGB 0..1); linearly interpolated for numeric colour.
_VIRIDIS = np.array(
    [
        [0.267, 0.005, 0.329], [0.283, 0.141, 0.458], [0.254, 0.265, 0.530],
        [0.207, 0.372, 0.553], [0.164, 0.471, 0.558], [0.128, 0.567, 0.551],
        [0.135, 0.659, 0.518], [0.267, 0.749, 0.441],
    ],
    dtype="float32",
)
# Discrete palette for categorical colour (Okabe–Ito, colour-blind-safe).
_CATEGORICAL = np.array(
    [
        [0.90, 0.62, 0.00], [0.34, 0.71, 0.91], [0.00, 0.62, 0.45],
        [0.95, 0.90, 0.25], [0.00, 0.45, 0.70], [0.84, 0.37, 0.00],
        [0.80, 0.47, 0.65], [0.40, 0.40, 0.40],
    ],
    dtype="float32",
)
_SOLID = (0.35, 0.60, 0.95, 0.90)  # default single colour
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


def _viridis(t: np.ndarray) -> np.ndarray:
    """Map t in [0,1] to rgba via the viridis stops."""
    t = np.clip(t, 0.0, 1.0)
    pos = t * (len(_VIRIDIS) - 1)
    lo = np.floor(pos).astype(int)
    hi = np.minimum(lo + 1, len(_VIRIDIS) - 1)
    frac = (pos - lo).reshape(-1, 1)
    rgb = _VIRIDIS[lo] * (1 - frac) + _VIRIDIS[hi] * frac
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


def build(df, spec, max_points: int = 150_000, seed: int = 0) -> RenderData:
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

    colors, legend = _colors(sub, spec, idx, take, len(pos))
    return RenderData(pos, colors, spec.is_3d, tuple(spec.axes), legend,
                      n_total, len(pos))


def _colors(sub, spec, idx, take, n):
    if not spec.color:
        colors = np.tile(np.array(_SOLID, dtype="float32"), (n, 1))
        return colors, None

    s = sub[spec.color]
    if s.dtype.is_numeric():
        vals = take(s.to_numpy().astype("float32"))
        finite = np.isfinite(vals)
        lo = float(np.min(vals[finite])) if finite.any() else 0.0
        hi = float(np.max(vals[finite])) if finite.any() else 1.0
        span = (hi - lo) or 1.0
        t = np.where(finite, (vals - lo) / span, 0.0)
        colors = _viridis(t)
        colors[~finite] = _NULL_RGBA  # nulls shown neutral, not dropped
        colors[:, 3] = 0.9
        return colors, ("colorbar", lo, hi, spec.color)

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
    colors[:, 3] = 0.9
    legend = [
        (str(v), tuple(pal[i % len(pal)]) + (0.9,))
        for i, v in enumerate(uniques)
    ]
    return colors, legend
