"""What a plot is: a type and which columns map to its channels.

Deliberately dumb — any column can go on any axis or the colour channel. The
defaults below are only a starting point for the dialog; nothing is hardcoded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SCATTER_2D = "2D Scatter"
SCATTER_3D = "3D Scatter"
BAR = "Bar"
HISTOGRAM = "Histogram"
LAYER_VIEWER = "Layer Viewer"
SINGLE_LAYER = "Single Layer"
COV_SUMMARY = "CoV Summary"
CONTOUR = "Contour"
KDE = "KDE"
KDIST = "K-Distance Curve"
VIOLIN = "Violin"
MEAN_SD = "Mean ± SD"
# the wired plot types
PLOT_KINDS = (
    SCATTER_2D, SCATTER_3D, LAYER_VIEWER, SINGLE_LAYER,
    BAR, HISTOGRAM, COV_SUMMARY, CONTOUR, KDE, KDIST, VIOLIN, MEAN_SD,
)

BAR_AGGS = ("as-is", "mean", "median", "sum", "min", "max", "count", "first")
# CoV Summary: how the coefficient of variation is reduced per group.
COV_MODES = ("overall", "per_layer_mean", "across_layers")
# KDE / violin: how the kernel's width is chosen (as scipy's gaussian_kde).
BANDWIDTHS = ("scott", "silverman")
# Mean ± SD: what the error bars show (sample SD, standard error, 95% CI).
ERRORS = ("sd", "se", "ci95", "none")
ERROR_NAMES = {"sd": "SD", "se": "SE", "ci95": "95% CI", "none": "None"}
# 2D Scatter with one point per group: what each axis shows of a group's rows.
STATS = ("mean", "median", "sd", "cov", "min", "max")
STAT_NAMES = {"mean": "Mean", "median": "Median", "sd": "SD", "cov": "CoV (%)",
              "min": "Min", "max": "Max"}


@dataclass
class PlotSpec:
    kind: str
    x: str
    y: str
    z: str | None = None
    color: str | None = None  # None = single colour
    agg: str = "mean"         # bar only: how to reduce the value per category
    bins: int = 30            # histogram / contour: bin or contour-level count
    group_by: str | None = None   # cov / kde / mean-sd: the grouping column
    cov_mode: str = "overall"     # cov: overall | per_layer_mean | across_layers
    show_points: bool = True      # contour: overlay the measured (x, y) points
    bandwidth: str = "scott"      # kde / violin: scott | silverman
    show_box: bool = True         # violin: quartile box + median inside
    k: int = 10                   # k-distance: which neighbour (= min_samples)
    eps_xy: float = 1.0           # k-distance: DBSCAN's XY radius (Z scaling,
    eps_z: float = 1.0            #   and the guide line) and its Z radius
    more_y: tuple = ()            # mean-sd: value columns after y (repeats)
    per: str | None = None        # 2d scatter: one point per value of this
    x_stat: str = "mean"          #   column, its X / Y the group's statistic
    y_stat: str = "mean"          #   (STATS) of the X / Y column's rows
    # Changed from the plot's toolbar after it is made:
    fill: bool = True             # kde: shade under the curves
    sort: str = "name"            # bar / cov: order the bars by name | value
    show_lines: bool = True       # contour: level lines between the bands
    show_ref: bool = True         # k-distance: the knee line (suggested eps)
    error: str = "sd"             # mean-sd: sd | se | ci95 | none
    fit: bool = False             # 2d scatter / mean-sd: the trend line
    shape_by: str | None = None   # 2d scatter / mean-sd: marker shape per value
    label_by: str | None = None   # 2d scatter / mean-sd: a text by each point
    x_error: bool = False         # mean-sd: error bars on X too (across parts)

    def __post_init__(self) -> None:
        self.more_y = tuple(self.more_y or ())  # a list, from JSON

    @property
    def is_3d(self) -> bool:
        return self.kind == SCATTER_3D

    @property
    def is_bar(self) -> bool:
        return self.kind == BAR

    @property
    def is_hist(self) -> bool:
        return self.kind == HISTOGRAM

    @property
    def is_layer_viewer(self) -> bool:
        return self.kind == LAYER_VIEWER

    @property
    def is_single_layer(self) -> bool:
        return self.kind == SINGLE_LAYER

    @property
    def is_cov(self) -> bool:
        return self.kind == COV_SUMMARY

    @property
    def is_contour(self) -> bool:
        return self.kind == CONTOUR

    @property
    def is_kde(self) -> bool:
        return self.kind == KDE

    @property
    def is_kdist(self) -> bool:
        return self.kind == KDIST

    @property
    def is_violin(self) -> bool:
        return self.kind == VIOLIN

    @property
    def is_meansd(self) -> bool:
        return self.kind == MEAN_SD

    @property
    def is_per(self) -> bool:
        """A 2D scatter of one point per group (``per``)."""
        return self.kind == SCATTER_2D and bool(self.per)

    @property
    def is_grouped(self) -> bool:
        """One point per group (Mean ± SD, a scatter of one point per group):
        a handful of summary points, not positions."""
        return self.is_meansd or self.is_per

    @property
    def can_fit(self) -> bool:
        """Whether this kind of plot can show a trend line."""
        return self.kind in (SCATTER_2D, MEAN_SD)

    @property
    def values(self) -> list[str]:
        """Mean ± SD: every value column (y, then the repeats)."""
        return list(dict.fromkeys(c for c in (self.y, *self.more_y) if c))

    @property
    def columns(self) -> list[str]:
        """Every column name the spec refers to (some may not be columns:
        a histogram's "count", a KDE's "density")."""
        return list(dict.fromkeys(
            c for c in (self.x, self.y, self.z, self.color, self.group_by,
                        *self.more_y, self.per, self.shape_by, self.label_by)
            if c))

    @property
    def is_curve(self) -> bool:
        """Drawn as lines over a numeric x (KDE, k-distance)."""
        return self.kind in (KDE, KDIST)

    @property
    def uses_y(self) -> bool:
        """Whether ``y`` names a data column (a histogram counts and a KDE
        estimates density; neither reads a y column)."""
        return self.kind not in (HISTOGRAM, KDE)

    @property
    def axes(self) -> list[str]:
        return [self.x, self.y, self.z] if self.is_3d else [self.x, self.y]


def default_spec(kind: str, columns: list[str], renames=None,
                 dbscan=None) -> PlotSpec:
    """A reasonable starting spec — preferred names if present, else positional.

    ``renames`` (original datastore name -> current display name) maps the
    hardcoded preferred names, so a renamed column is still picked as a default.
    ``dbscan`` is the build's (eps_xy, eps_z, min_samples), for the k-distance
    curve to start from what the build's DBSCAN would use.
    """
    cols = list(columns)
    ren = renames or {}

    def pick(preferred: str, index: int) -> str:
        disp = ren.get(preferred, preferred)
        if disp in cols:
            return disp
        return cols[index] if index < len(cols) else (cols[0] if cols else "")

    if kind == BAR:
        # Category: a label-ish column if present; Value: melt pool (mean).
        cat = next((ren.get(c, c) for c in ("region", "side", "part_id")
                    if ren.get(c, c) in cols), cols[0] if cols else "")
        val = _default_color(cols, ren) or pick("Z", 1)
        return PlotSpec(kind=kind, x=cat, y=val, agg="mean")

    if kind == HISTOGRAM:
        # Bin a numeric column; Y is the count.
        col = _default_color(cols, ren) or pick("Z", 0)
        return PlotSpec(kind=kind, x=col, y="count", bins=30)

    if kind == COV_SUMMARY:
        # One bar per group (part) of a signal's coefficient of variation.
        grp = next((ren.get(c, c) for c in ("part_id", "region", "side")
                    if ren.get(c, c) in cols), cols[0] if cols else "")
        sig = _default_color(cols, ren) or pick("Z", 1)
        return PlotSpec(kind=kind, x=grp, y=sig, group_by=grp,
                        cov_mode="overall")

    if kind == KDE:
        # Density of a signal, one curve per part when parts are assigned.
        col = _default_color(cols, ren) or pick("Z", 0)
        grp = next((ren.get(c, c) for c in ("part_id", "region", "side")
                    if ren.get(c, c) in cols), None)
        return PlotSpec(kind=kind, x=col, y="density", group_by=grp)

    if kind == VIOLIN:
        # A signal's distribution per category (part, label, layer).
        cat = next((ren.get(c, c) for c in ("part_id", "region", "side", "layer")
                    if ren.get(c, c) in cols), cols[0] if cols else "")
        val = _default_color(cols, ren) or pick("Z", 1)
        return PlotSpec(kind=kind, x=cat, y=val)

    if kind == KDIST:
        # DBSCAN's neighbourhood: positions (and Z), its eps and min_samples.
        eps_xy, eps_z, k = dbscan or (0.3, 0.06, 10)
        z = ren.get("Z", "Z")
        return PlotSpec(kind=kind, x=pick("Demand X", 0), y=pick("Demand Y", 1),
                        z=z if z in cols else None, k=int(k),
                        eps_xy=float(eps_xy), eps_z=float(eps_z))

    if kind == MEAN_SD:
        # One point per part: a per-part value (a density imported from the
        # samples template, say) and its repeats, over a process column.
        grp = ren.get("part_id", "part_id")
        x = next((c for c in cols if "energy" in c.lower()), None) or pick(
            "Hatches Power", 0)
        sets = repeat_sets(cols)
        best = next((s for s in sets if "densit" in s[0].lower()),
                    sets[0] if sets else None)
        y, more = (best[0], tuple(best[1:])) if best else (pick("Z", 1), ())
        return PlotSpec(kind=kind, x=x, y=y, more_y=more,
                        group_by=grp if grp in cols else None)

    if kind == CONTOUR:
        # A value (z) over an (x, y) parameter grid; default to parametric
        # process columns when present, else the first numeric columns.
        cx = pick("Hatch Speed", 0)
        cy = pick("Hatches Power", 1)
        cz = _default_color(cols, ren) or pick("Z", 2)
        return PlotSpec(kind=kind, x=cx, y=cy, z=cz, show_points=True, bins=14)

    x = pick("Demand X", 0)
    y = pick("Demand Y", 1)
    z = pick("Z", 2) if kind == SCATTER_3D else None
    color = _default_color(cols, ren)
    return PlotSpec(kind=kind, x=x, y=y, z=z, color=color)


_REPEAT = re.compile(r"[\s_\-]*(\(\d+\)|\d+)$")


def repeat_base(name: str) -> str:
    """A repeat column's shared name: ``Density (2)`` / ``Density_2`` ->
    ``Density`` (a name without a number is its own base)."""
    return _REPEAT.sub("", str(name)).strip() or str(name)


def repeat_sets(columns) -> list[list[str]]:
    """Columns that are numbered repeats of one measurement (two or more
    sharing a base name, each with a number), in column order."""
    sets: dict[str, list[str]] = {}
    for c in columns:
        if _REPEAT.search(str(c)) and repeat_base(c) != str(c):
            sets.setdefault(repeat_base(c).lower(), []).append(c)
    return [s for s in sets.values() if len(s) >= 2]


def _default_color(columns: list[str], renames=None) -> str | None:
    """Default colour channel: the melt-pool (mean) column when present."""
    mp = (renames or {}).get("MeltVIEW melt pool (mean)",
                             "MeltVIEW melt pool (mean)")
    if mp in columns:
        return mp
    for c in columns:  # tolerate a differently-prefixed name
        if "melt pool (mean)" in c.lower():
            return c
    return None
