"""What a plot is: a type and which columns map to its channels.

Deliberately dumb — any column can go on any axis or the colour channel. The
defaults below are only a starting point for the dialog; nothing is hardcoded.
"""

from __future__ import annotations

from dataclasses import dataclass

SCATTER_2D = "2D Scatter"
SCATTER_3D = "3D Scatter"
SCATTER_KINDS = (SCATTER_2D, SCATTER_3D)


@dataclass
class PlotSpec:
    kind: str
    x: str
    y: str
    z: str | None = None
    color: str | None = None  # None = single colour

    @property
    def is_3d(self) -> bool:
        return self.kind == SCATTER_3D

    @property
    def axes(self) -> list[str]:
        return [self.x, self.y, self.z] if self.is_3d else [self.x, self.y]


def default_spec(kind: str, columns: list[str]) -> PlotSpec:
    """A reasonable starting spec — preferred names if present, else positional."""
    cols = list(columns)

    def pick(preferred: str, index: int) -> str:
        if preferred in cols:
            return preferred
        return cols[index] if index < len(cols) else (cols[0] if cols else "")

    x = pick("Demand X", 0)
    y = pick("Demand Y", 1)
    z = pick("Z", 2) if kind == SCATTER_3D else None
    color = _default_color(cols)
    return PlotSpec(kind=kind, x=x, y=y, z=z, color=color)


def _default_color(columns: list[str]) -> str | None:
    """Default colour channel: the melt-pool (mean) column when present."""
    if "MeltVIEW melt pool (mean)" in columns:
        return "MeltVIEW melt pool (mean)"
    for c in columns:  # tolerate a differently-prefixed name
        if "melt pool (mean)" in c.lower():
            return c
    return None
