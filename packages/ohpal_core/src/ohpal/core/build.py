"""
Reader for the machine build file and the part-identity primitives that both
``ohpal.samples`` and ``ohpal.ampm`` build on.

This module owns two things that used to live in ``ohpal.ampm.parts``:

  * :class:`BuildParts` — parses a Renishaw "BuildStarted" ``.dhxml`` file
    (JSON despite the extension) into per-part names and 3D bounding boxes.
  * the point-in-bounding-box primitive (:meth:`BuildParts.part_at` /
    :meth:`BuildParts.part_ids_at`) used to resolve a physical origin to the
    part_id the machine assigned.

It lives in ``ohpal.core`` so both packages can depend on it without a cycle
(``ohpal.samples`` never imports ``ohpal.ampm``). The canonical join key is
``part_id`` as ``Utf8`` — this module is the single place that spelling is
minted, so downstream code never has to reconcile ``Part ID`` vs ``part_id``.

Dependencies are deliberately light (numpy + polars only). The KDTree-backed
*bulk* point-cloud assignment stays in ``ohpal.ampm``, which already carries
scipy; here we only need the exact, few-origins containment test.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np
import polars as pl

__all__ = [
    "BuildParts",
    "BuildFileError",
    "PartResolutionError",
    "DUP_SUFFIX",
]

# Paths into the BuildStarted JSON document.
_DHXML_BUILD_PATH = ("version1", "build")
_DHXML_PARTS_PATH = ("version1", "build", "parts")

# Format used to make a repeated part name unique: ``name#n`` in file order.
# This is a CROSS-PACKAGE contract: the lookup-table tool in ohpal.samples must
# emit the identical scheme so a copied part_id matches what the resolver mints.
DUP_SUFFIX = "{name}#{n}"


class BuildFileError(ValueError):
    """The build file is missing, unreadable, or not a recognised layout."""


class PartResolutionError(ValueError):
    """An origin could not be resolved to exactly one part.

    Raised on both *no* containing box (outside every part, beyond tolerance)
    and *more than one* containing box (overlapping/ambiguous). Identity is
    load-bearing, so this never silently guesses.
    """


def _parse_bounding_box(value: str | list) -> tuple[float, ...]:
    """Parse a ``"xmin,ymin,zmin,xmax,ymax,zmax"`` box, normalised min<=max."""
    fields = value.split(",") if isinstance(value, str) else list(value)

    if len(fields) != 6:
        raise ValueError(f"expected 6 comma-separated numbers, got {value!r}")

    xmin, ymin, zmin, xmax, ymax, zmax = (float(v) for v in fields)

    return (
        min(xmin, xmax),
        min(ymin, ymax),
        min(zmin, zmax),
        max(xmin, xmax),
        max(ymin, ymax),
        max(zmin, zmax),
    )


def _suffix_duplicate_names(parts: list[dict]) -> list[dict]:
    """Add a unique ``part_id`` per part, suffixing repeated names ``name#n``.

    Names that appear once keep their name as the part_id; names that repeat get
    ``name#1``, ``name#2``, ... in file order.
    """
    counts = Counter(p["name"] for p in parts)
    seen: Counter = Counter()
    out: list[dict] = []

    for p in parts:
        name = p["name"]
        if counts[name] > 1:
            seen[name] += 1
            part_id = DUP_SUFFIX.format(name=name, n=seen[name])
        else:
            part_id = name
        out.append({**p, "part_id": part_id})

    return out


class BuildParts:
    """Per-part names and 3D bounding boxes from a "BuildStarted" ``.dhxml``.

    Load with :meth:`from_dhxml`. Repeated part names are made unique by
    suffixing ``name#n`` in file order (see :func:`_suffix_duplicate_names`);
    the canonical, unique key is ``part_id``.
    """

    def __init__(
        self,
        parts: list[dict],
        raw: dict | None = None,
        path: Path | None = None,
    ) -> None:
        self._parts = parts
        self._raw = raw
        self.path = path

        # Column-parallel numpy arrays for the containment primitive. Small
        # (one row per part), built once so per-origin lookups are cheap.
        self._part_ids = [p["part_id"] for p in parts]
        self._names = [p["name"] for p in parts]
        self._boxes = np.array([p["bbox"] for p in parts], dtype=np.float64)
        # columns: 0=xmin 1=ymin 2=zmin 3=xmax 4=ymax 5=zmax

    @classmethod
    def from_dhxml(cls, path: str | Path) -> "BuildParts":
        """Load and parse a BuildStarted ``.dhxml`` (JSON) file."""
        path = Path(path)
        if not path.is_file():
            raise BuildFileError(f"BuildStarted DHXML not found:\n{path}")

        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as e:
            raise BuildFileError(
                f"{path} is not valid JSON; is this a BuildStarted DHXML? ({e})"
            ) from e

        node = raw
        for key in _DHXML_PARTS_PATH:
            if not isinstance(node, dict) or key not in node:
                raise BuildFileError(
                    f"{path} is not a recognised BuildStarted DHXML: "
                    f"missing {'/'.join(_DHXML_PARTS_PATH)!r}."
                )
            node = node[key]

        if not isinstance(node, list) or not node:
            raise BuildFileError(f"No parts listed in {path}.")

        parsed: list[dict] = []
        for i, entry in enumerate(node):
            try:
                name = str(entry["name"])
                bbox = _parse_bounding_box(entry["boundingBox"])
            except (KeyError, TypeError, ValueError) as e:
                raise BuildFileError(
                    f"Malformed part entry #{i} in {path}: {entry!r} ({e})"
                ) from e
            parsed.append({"name": name, "bbox": bbox})

        return cls(_suffix_duplicate_names(parsed), raw=raw, path=path)

    # Back-compat alias for callers migrating from BuildStartedDHXML.from_path.
    from_path = from_dhxml

    @property
    def part_ids(self) -> list[str]:
        """Canonical, unique part identifiers (post-suffix), in file order."""
        return list(self._part_ids)

    @property
    def part_names(self) -> list[str]:
        """Original (pre-suffix) part names, in file order."""
        return list(self._names)

    def _build_node(self) -> dict | None:
        node = self._raw
        for key in _DHXML_BUILD_PATH:
            if not isinstance(node, dict) or key not in node:
                return None
            node = node[key]
        return node if isinstance(node, dict) else None

    @property
    def mtt_filename(self) -> str | None:
        """The build's ``.mtt`` file name from the dhxml, if present."""
        node = self._build_node()
        value = node.get("mttFileName") if node else None
        return value or None  # treat "" as absent

    @property
    def build_name(self) -> str | None:
        """The build's ``name`` field from the dhxml, if non-empty."""
        node = self._build_node()
        value = node.get("name") if node else None
        return value or None

    @property
    def build_id(self) -> str | None:
        """Best available build identifier.

        The mtt file name's stem (e.g. ``JR299_OHP_Ti-Sterling.mtt`` ->
        ``JR299_OHP_Ti-Sterling``), falling back to the build ``name``, else
        None. part_id is only unique *within* a build, so this is the natural
        disambiguator when per-part data is merged across builds.
        """
        if self.mtt_filename:
            return Path(self.mtt_filename).stem
        return self.build_name

    def __len__(self) -> int:
        return len(self._parts)

    def __repr__(self) -> str:
        path = f", path={self.path!s}" if self.path else ""
        return f"BuildParts(parts={len(self._parts)}{path})"

    def parts_table(self) -> pl.DataFrame:
        """One row per part with canonical, neutral column names.

        Columns: ``part_id`` (Utf8), ``name`` (Utf8, pre-suffix),
        box corners ``{x,y,z}_{min,max}`` and XY centre ``x_center``/
        ``y_center`` (all Float64).

        ``ohpal.ampm`` renames these to its QuantAM spelling in a thin adapter;
        core stays neutral so ``ohpal.samples`` doesn't inherit QuantAM naming.
        """
        b = self._boxes
        return pl.DataFrame(
            {
                "part_id": pl.Series(self._part_ids, dtype=pl.String),
                "name": pl.Series(self._names, dtype=pl.String),
                "x_min": pl.Series(b[:, 0], dtype=pl.Float64),
                "y_min": pl.Series(b[:, 1], dtype=pl.Float64),
                "z_min": pl.Series(b[:, 2], dtype=pl.Float64),
                "x_max": pl.Series(b[:, 3], dtype=pl.Float64),
                "y_max": pl.Series(b[:, 4], dtype=pl.Float64),
                "z_max": pl.Series(b[:, 5], dtype=pl.Float64),
            }
        ).with_columns(
            ((pl.col("x_min") + pl.col("x_max")) / 2.0).alias("x_center"),
            ((pl.col("y_min") + pl.col("y_max")) / 2.0).alias("y_center"),
        )

    # ---- containment primitive -------------------------------------------

    def _containing(self, x: float, y: float, z: float | None, use_z: bool) -> np.ndarray:
        """Indices of every part whose bounding box contains ``(x, y[, z])``."""
        b = self._boxes
        inside = (x >= b[:, 0]) & (x <= b[:, 3]) & (y >= b[:, 1]) & (y <= b[:, 4])
        if use_z:
            if z is None:
                raise ValueError("use_z=True requires a z coordinate")
            inside &= (z >= b[:, 2]) & (z <= b[:, 5])
        return np.flatnonzero(inside)

    def _distance_to_boxes(self, x: float, y: float) -> np.ndarray:
        """2D distance from a point to each AABB (0 if inside), for tolerance."""
        b = self._boxes
        dx = np.maximum.reduce([b[:, 0] - x, np.zeros(len(b)), x - b[:, 3]])
        dy = np.maximum.reduce([b[:, 1] - y, np.zeros(len(b)), y - b[:, 4]])
        return np.hypot(dx, dy)

    def part_at(
        self,
        x: float,
        y: float,
        z: float | None = None,
        *,
        use_z: bool = False,
        tol: float = 0.0,
    ) -> str:
        """Resolve a single origin to exactly one ``part_id``.

        Exact point-in-bounding-box. Policy is strict, because identity feeds a
        join key:

          * exactly one containing box   -> that part_id
          * more than one containing box -> :class:`PartResolutionError`
            (overlapping/ambiguous; never guesses)
          * no containing box            -> if ``tol > 0`` and a *single* box is
            within ``tol`` mm of the point, that part_id; otherwise
            :class:`PartResolutionError`

        ``z`` is degenerate on typical builds (every part spans the full height),
        so matching is 2D by default; pass ``use_z=True`` to also gate on Z.
        """
        hits = self._containing(x, y, z, use_z)

        if hits.size == 1:
            return self._part_ids[int(hits[0])]

        if hits.size > 1:
            cand = [self._part_ids[i] for i in hits]
            raise PartResolutionError(
                f"origin ({x}, {y}) lies inside {hits.size} overlapping part "
                f"boxes {cand}; cannot resolve unambiguously"
            )

        # No containing box: optional tolerance fallback to a *unique* nearest.
        if tol > 0.0:
            dist = self._distance_to_boxes(x, y)
            order = np.argsort(dist)
            nearest, second = dist[order[0]], (dist[order[1]] if len(order) > 1 else np.inf)
            if nearest <= tol and nearest < second:
                return self._part_ids[int(order[0])]
            if nearest <= tol:
                raise PartResolutionError(
                    f"origin ({x}, {y}) is within tol={tol} of two parts equally "
                    f"({dist[order[0]]:.4g} mm); cannot resolve unambiguously"
                )

        raise PartResolutionError(
            f"origin ({x}, {y}) lies inside no part box"
            + (f" (nearest {self._distance_to_boxes(x, y).min():.4g} mm > tol={tol})" if tol else "")
        )

    def part_ids_at(
        self,
        df: pl.DataFrame,
        *,
        x_col: str = "x",
        y_col: str = "y",
        z_col: str = "z",
        use_z: bool = False,
        tol: float = 0.0,
        out_col: str = "part_id",
    ) -> pl.DataFrame:
        """Add a ``part_id`` column by resolving each row's origin via :meth:`part_at`.

        Convenience for the ``ohpal.samples`` spatial resolver: one call turns a
        table of origins into the same table plus a canonical ``part_id`` (Utf8).
        Any unresolved row raises (hard fail), consistent with the identity chain.
        """
        for c in (x_col, y_col, *( (z_col,) if use_z else () )):
            if c not in df.columns:
                raise KeyError(f"Column {c!r} not in DataFrame")

        xs = df[x_col].to_list()
        ys = df[y_col].to_list()
        zs = df[z_col].to_list() if use_z else [None] * len(xs)

        ids = [
            self.part_at(x, y, z, use_z=use_z, tol=tol)
            for x, y, z in zip(xs, ys, zs)
        ]
        return df.with_columns(pl.Series(out_col, ids, dtype=pl.String))
