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
KDE = "KDE"
KDIST = "K-Distance Curve"
VIOLIN = "Violin"
# the wired plot types
PLOT_KINDS = (
    SCATTER_2D, SCATTER_3D, LAYER_VIEWER, SINGLE_LAYER,
    BAR, HISTOGRAM, COV_SUMMARY, CONTOUR, KDE, KDIST, VIOLIN,
)

BAR_AGGS = ("as-is", "mean", "median", "sum", "min", "max", "count", "first")
# CoV Summary: how the coefficient of variation is reduced per group.
COV_MODES = ("overall", "per_layer_mean", "across_layers")
# KDE / violin: how the kernel's width is chosen (as scipy's gaussian_kde).
BANDWIDTHS = ("scott", "silverman")


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
    bandwidth: str = "scott"      # kde / violin: scott | silverman
    show_box: bool = True         # violin: quartile box + median inside
    k: int = 10                   # k-distance: which neighbour (= min_samples)
    eps_xy: float = 1.0           # k-distance: DBSCAN's XY radius (Z scaling,
    eps_z: float = 1.0            #   and the guide line) and its Z radius
    # Changed from the plot's toolbar after it is made:
    fill: bool = True             # kde: shade under the curves
    sort: str = "name"            # bar / cov: order the bars by name | value
    show_lines: bool = True       # contour: level lines between the bands
    show_ref: bool = True         # k-distance: the dashed eps guide

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
