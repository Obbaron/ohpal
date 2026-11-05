"""What a plot is: a type and which columns map to its channels.

Deliberately dumb — any column can go on any axis or the colour channel. The
defaults below are only a starting point for the dialog; nothing is hardcoded.
"""

from __future__ import annotations

from dataclasses import dataclass

SCATTER_2D = "2D Scatter"
SCATTER_3D = "3D Scatter"
BAR = "Bar"
HISTOGRAM = "Histogram"
LAYER_VIEWER = "Layer Viewer"
SINGLE_LAYER = "Single Layer"
COV_SUMMARY = "CoV Summary"
CONTOUR = "Contour"
SCATTER_KINDS = (SCATTER_2D, SCATTER_3D)
# the wired plot types
PLOT_KINDS = (
    SCATTER_2D, SCATTER_3D, LAYER_VIEWER, SINGLE_LAYER,
    BAR, HISTOGRAM, COV_SUMMARY, CONTOUR,
)

BAR_AGGS = ("as-is", "mean", "median", "sum", "min", "max", "count", "first")
# CoV Summary: how the coefficient of variation is reduced per group.
COV_MODES = ("overall", "per_layer_mean", "across_layers")


@dataclass
class PlotSpec:
    kind: str
    x: str
    y: str
    z: str | None = None
    color: str | None = None  # None = single colour
    agg: str = "mean"         # bar only: how to reduce the value per category
    bins: int = 30            # histogram / contour: bin or contour-level count
    group_by: str | None = None   # cov: the grouping column (x = one bar per)
    cov_mode: str = "overall"     # cov: overall | per_layer_mean | across_layers
    show_points: bool = True      # contour: overlay the measured (x, y) points

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
    def axes(self) -> list[str]:
        return [self.x, self.y, self.z] if self.is_3d else [self.x, self.y]


def default_spec(kind: str, columns: list[str], renames=None) -> PlotSpec:
    """A reasonable starting spec — preferred names if present, else positional.

    ``renames`` (original datastore name -> current display name) maps the
    hardcoded preferred names, so a renamed column is still picked as a default.
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
