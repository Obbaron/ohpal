"""
DataStore: lazy-loading, Parquet-cached access to Renishaw 500S AMPM data.

A directory of 'Packet data for layer N, laser M.txt' files is converted on first
use to a partitioned Parquet dataset (one file per layer) under <source_dir>/.cache/.
Queries use Polars' lazy API so only the requested slice is materialized in memory.

Two DataHUB export layouts are read: the current one (``EXPECTED_COLUMNS``,
mean and median of each signal) and the older one (``LEGACY_COLUMNS``: seven
columns, renamed on reading to their current names). Only ``REQUIRED_COLUMNS``
must be present; a build carries just the known columns its files have, and
every layer of a build must have the same ones.
"""

from __future__ import annotations

import numbers
import re
from pathlib import Path
from typing import Iterable

import polars as pl

CACHE_FORMAT_VERSION = 2

EXPECTED_COLUMNS: list[str] = [
    "Start time",
    "Duration",
    "Demand X",
    "Demand Y",
    "Demand focus",
    "Demand laser power (mean)",
    "MeltVIEW plasma (mean)",
    "MeltVIEW melt pool (mean)",
    "LaserVIEW (mean)",
    "Laser back reflection (mean)",
    "Laser output power (mean)",
    "Demand laser power (median)",
    "MeltVIEW plasma (median)",
    "MeltVIEW melt pool (median)",
    "LaserVIEW (median)",
    "Laser back reflection (median)",
    "Laser output power (median)",
]

# The DataHUB's older packet export: its column names and the current columns
# they hold (LaserVIEW there is the same signal as LaserVIEW (mean) now). It
# has no focus, laser power, back reflection or median columns.
LEGACY_COLUMNS: dict[str, str] = {
    "Start time / us": "Start time",
    "Duration / us": "Duration",
    "x position / mm": "Demand X",
    "y position / mm": "Demand Y",
    "LaserVIEW": "LaserVIEW (mean)",
    "MeltVIEW Plasma": "MeltVIEW plasma (mean)",
    "MeltVIEW Melt Pool": "MeltVIEW melt pool (mean)",
}

# What every layer must have (after renaming): the row key (layer + Start
# time), the position, and Duration for a stacked build's timing. The other
# known columns are kept when present.
REQUIRED_COLUMNS: list[str] = ["Start time", "Duration", "Demand X", "Demand Y"]

CURRENT = "current"
LEGACY = "legacy"
LAYOUT_NAMES = {CURRENT: "current DataHUB layout",
                LEGACY: "older DataHUB layout"}


class Layout:
    """One packet file's column layout, read from its header line.

    ``kind`` is ``CURRENT`` or ``LEGACY``; ``renames`` maps the file's own
    header names to their current names; ``columns`` are the known columns the
    file has (current names, in ``EXPECTED_COLUMNS`` order); ``header`` is the
    file's header as written.
    """

    def __init__(self, header: list[str]) -> None:
        self.header = [h for h in header if h.strip()]
        names = {h.strip() for h in self.header}
        legacy = (any(n in LEGACY_COLUMNS for n in names)
                  and not any(n in EXPECTED_COLUMNS for n in names))
        self.kind = LEGACY if legacy else CURRENT
        self.renames = ({h: LEGACY_COLUMNS[h.strip()] for h in self.header
                         if h.strip() in LEGACY_COLUMNS} if legacy
                        else {h: h.strip() for h in self.header if h != h.strip()})
        have = {self.renames.get(h, h) for h in self.header}
        self.columns = [c for c in EXPECTED_COLUMNS if c in have]
        self.missing = [c for c in REQUIRED_COLUMNS if c not in have]

    @property
    def name(self) -> str:
        return LAYOUT_NAMES[self.kind]

    def same_as(self, other: Layout) -> bool:
        return self.kind == other.kind and self.columns == other.columns

    def describe(self) -> str:
        return f"the {self.name}, {len(self.columns)} columns"


def read_layout(path: str | Path) -> Layout:
    """The layout of one packet file, from its first line (cheap)."""
    with open(path, encoding="utf-8-sig", errors="replace") as fh:
        line = fh.readline()
    return Layout(line.rstrip("\r\n").split("\t"))


_CSV_SCHEMA_2: dict[str, type[pl.DataType]] = {
    "Start time": pl.Int32,
    "Duration": pl.Int16,
    "Demand X": pl.Float32,
    "Demand Y": pl.Float32,
    "Demand focus": pl.Float32,
    "Demand laser power (mean)": pl.Float32,
    "MeltVIEW plasma (mean)": pl.Float32,
    "MeltVIEW melt pool (mean)": pl.Float32,
    "LaserVIEW (mean)": pl.Float32,
    "Laser back reflection (mean)": pl.Float32,
    "Laser output power (mean)": pl.Float32,
    "Demand laser power (median)": pl.Float32,
    "MeltVIEW plasma (median)": pl.Float32,
    "MeltVIEW melt pool (median)": pl.Float32,
    "LaserVIEW (median)": pl.Float32,
    "Laser back reflection (median)": pl.Float32,
    "Laser output power (median)": pl.Float32,
}

_FILENAME_RE = re.compile(
    r"^Packet data for layer (\d+), laser \d+\.txt$",
    re.IGNORECASE,
)


def _missing_message(layer: int, src: Path, layout: Layout) -> str:
    return (
        f"Layer {layer} ({src.name}) is missing required columns: "
        f"{layout.missing}\nFound columns: {[h.strip() for h in layout.header]}\n"
        f"Packet data must be a DataHUB export, in the current layout or the "
        f"older one ({', '.join(LEGACY_COLUMNS)})."
    )


def _mixed_message(first: int, base: Layout, layer: int, other: Layout) -> str:
    if base.kind != other.kind:
        what = (f"layer {first} is in the {base.name} and layer {layer} in the "
                f"{other.name}")
    else:
        extra = [c for c in other.columns if c not in base.columns]
        lost = [c for c in base.columns if c not in other.columns]
        what = (f"layer {layer} has different columns from layer {first}"
                + (f" (extra: {extra})" if extra else "")
                + (f" (missing: {lost})" if lost else ""))
    return (f"This build mixes DataHUB exports: {what}. Every layer of a "
            f"build must have the same columns; export it again in one layout.")


class DataStore:
    """
    Lazy data store over a directory of AMPM Packet data text files.

    Parameters
    ----------
    source_dir : str | Path
        Directory containing the 'Packet data for layer N, laser M.txt' files.
    layer_thickness : float, default 0.03
        Layer thickness in mm. Used to compute the Z column as
        ``layer * layer_thickness``.
    cache_dir : str | Path | None, default None
        Directory for the Parquet cache. If None, uses ``source_dir / ".cache"``.
    """

    def __init__(
        self,
        source_dir: str | Path,
        layer_thickness: float = 0.03,
        cache_dir: str | Path | None = None,
    ) -> None:
        self.source_dir = Path(source_dir).resolve()
        if not self.source_dir.is_dir():
            raise FileNotFoundError(f"source_dir does not exist: {self.source_dir}")

        self.layer_thickness = float(layer_thickness)
        self.cache_dir = (
            Path(cache_dir).resolve()
            if cache_dir is not None
            else self.source_dir / ".cache"
        )

        self._source_files: dict[int, Path] = self._discover_source_files()
        # The build's column layout, from its first layer's header; every other
        # layer is checked against it before it is converted.
        first = min(self._source_files)
        self._layout = read_layout(self._source_files[first])
        if self._layout.missing:
            raise ValueError(_missing_message(
                first, self._source_files[first], self._layout))

        # Optional part assignment. When set, ``query`` attaches a ``part_id``
        # column — either by bounding-box containment (``"bbox"``, e.g. from a
        # .dhxml) or by nearest part centre (``"nearest"``, e.g. from a QuantAM
        # parts CSV) on (Demand X, Demand Y); see ``set_part_assignment``. Kept
        # out of the Parquet cache so switching the method never invalidates the
        # raw per-layer cache.
        self._parts_table: pl.DataFrame | None = None
        self._parts_method: str = "bbox"
        self._parts_max_dist: float | None = None

    def _discover_source_files(self) -> dict[int, Path]:
        """Find all matching .txt files in source_dir and map layer -> path."""
        out: dict[int, Path] = {}
        for p in self.source_dir.iterdir():
            if not p.is_file():
                continue
            m = _FILENAME_RE.match(p.name)
            if m is None:
                continue
            layer = int(m.group(1))
            if layer in out:
                raise ValueError(
                    f"Duplicate layer {layer}: {out[layer].name} and {p.name}"
                )
            out[layer] = p
        if not out:
            raise FileNotFoundError(
                f"No 'Packet data for layer N, laser M.txt' files found in "
                f"{self.source_dir}"
            )
        return out

    def _cache_path(self, layer: int) -> Path:
        """Return the Parquet path for a given layer."""
        return self.cache_dir / f"layer={layer:05d}.parquet"

    def cached_layers(self) -> set[int]:
        """The layers whose Parquet is in the cache (present, not checked for
        being up to date). One directory read, however many layers."""
        import os

        try:
            present = {e.name for e in os.scandir(self.cache_dir)
                       if e.name.endswith(".parquet")}
        except OSError:
            return set()
        return {L for L in self._source_files
                if self._cache_path(L).name in present}

    @property
    def layers(self) -> list[int]:
        """Sorted list of layer numbers discovered in source_dir."""
        return sorted(self._source_files.keys())

    @property
    def layout(self) -> Layout:
        """The build's DataHUB export layout (see ``Layout``)."""
        return self._layout

    @property
    def columns(self) -> list[str]:
        """Available data columns: the known source columns the build has (all
        of ``EXPECTED_COLUMNS`` for the current layout) + 'layer' + 'Z'.

        When a part assignment is active, ``part_id`` is appended — it is
        computed per query rather than stored in the cache.
        """
        base = [*self._layout.columns, "layer", "Z"]
        if self._parts_table is not None:
            base.append("part_id")
        return base

    def set_part_assignment(
        self,
        parts_table: pl.DataFrame | None,
        *,
        method: str = "bbox",
        max_distance_mm: float | None = None,
    ) -> None:
        """Enable (or clear) a part assignment.

        ``parts_table`` is a one-row-per-part table. With ``method="bbox"`` it
        carries ``part_id`` and the box corners (``x_min`` … ``y_max``), e.g.
        from ``BuildStartedDHXML(...).parts_table()``, and rows are assigned by
        containment (null outside every box). With ``method="nearest"`` it
        carries ``part_id`` and part centres (``x_center``/``y_center``), e.g.
        from ``QuantAMParts(...).parent_parts()``, and each row takes its
        nearest part's id; ``max_distance_mm`` (if given) nulls rows farther
        than that from any part. Pass ``None`` to disable.

        With ``method="labels"`` the table is not one row per part but one row
        per labelled *point* — ``layer``, ``Start time``, ``part_id`` (e.g. the
        outcome of a DBSCAN clustering) — and each queried row takes the id
        recorded for its own (layer, Start time); points without a label get
        null. The keys must be unique.
        """
        self._parts_table = parts_table
        self._parts_method = (method or "bbox").lower()
        self._parts_max_dist = max_distance_mm

    def _needs_rebuild(self, layer: int) -> bool:
        """
        True if the Parquet for this layer is missing, older than its source,
        written with an old cache format version, or built with a different
        layer thickness.
        """
        src = self._source_files[layer]
        cache = self._cache_path(layer)

        if not cache.exists():
            return True
        if src.stat().st_mtime > cache.stat().st_mtime:
            return True

        try:
            lf = pl.scan_parquet(str(cache), glob=False)
            schema = lf.collect_schema()
            if schema.get("Z") != pl.Float32:
                return True
            # Written for other columns (an older layout reading, say).
            if schema.names() != [*self._layout.columns, "layer", "Z"]:
                return True

            head = lf.select("layer", "Z").head(1).collect()
            if head.height:
                cached_layer = head["layer"][0]
                cached_z = head["Z"][0]
                expected_z = cached_layer * self.layer_thickness

                if abs(cached_z - expected_z) > 1e-4 * max(1.0, abs(expected_z)):
                    return True

        except Exception:
            return True

        return False

    def _check_layout(self, layer: int, layout: Layout) -> None:
        """Raise if ``layer``'s layout isn't the build's."""
        if layout.missing:
            raise ValueError(_missing_message(
                layer, self._source_files[layer], layout))
        if not layout.same_as(self._layout):
            raise ValueError(_mixed_message(
                min(self._source_files), self._layout, layer, layout))

    def check_layouts(
        self, layers: Iterable[int] | None = None, *, force: bool = False
    ) -> None:
        """Raise ``ValueError`` if a layer to be converted has a different
        layout from the build's (a build mixing DataHUB exports), before any
        is converted. Reads only the header line of each layer whose cache is
        missing or older than its source (every layer with ``force``)."""
        candidates = (self.layers if layers is None else
                      sorted({int(L) for L in layers} & set(self._source_files)))
        for layer in candidates:
            src = self._source_files[layer]
            cache = self._cache_path(layer)
            if (not force and cache.exists()
                    and cache.stat().st_mtime >= src.stat().st_mtime):
                continue
            self._check_layout(layer, read_layout(src))

    def _convert_one(self, layer: int) -> None:
        """Read one source .txt and write its Parquet sibling."""
        src = self._source_files[layer]
        layout = read_layout(src)
        self._check_layout(layer, layout)
        # Compact types by the file's own header names (an older layout's
        # names map to current ones); names not in the file are ignored.
        overrides = {h: _CSV_SCHEMA_2[layout.renames.get(h, h)]
                     for h in layout.header
                     if layout.renames.get(h, h) in _CSV_SCHEMA_2}
        df = pl.read_csv(
            src,
            separator="\t",
            has_header=True,
            truncate_ragged_lines=True,
            glob=False,  # path may contain '[3]' etc. that look like glob patterns
            schema_overrides=overrides,
        )

        drop_cols = [c for c in df.columns if c.strip() == ""]
        if drop_cols:
            df = df.drop(drop_cols)
        renames = {c: layout.renames[c] for c in df.columns if c in layout.renames}
        if renames:
            df = df.rename(renames)
        df = df.select(layout.columns)

        df = df.with_columns(
            pl.lit(layer, dtype=pl.Int16).alias("layer"),
            pl.lit(layer * self.layer_thickness, dtype=pl.Float32).alias("Z"),
        )

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        df.write_parquet(
            self._cache_path(layer),
            compression="zstd",
        )

    def build_cache(
        self,
        layers: Iterable[int] | None = None,
        force: bool = False,
        verbose: bool = True,
    ) -> None:
        """
        Convert source .txt files to Parquet. Skips files whose Parquet is
        already up-to-date (by mtime) unless ``force=True``.

        Parameters
        ----------
        layers
            If given, only build cache for these layer numbers. If None,
            consider every discovered layer.
        force
            If True, rebuild even up-to-date cache files.
        verbose
            Print progress messages.
        """
        if layers is None:
            candidates = self.layers
        else:
            candidates = sorted(set(int(L) for L in layers) & set(self._source_files))

        to_build = [L for L in candidates if force or self._needs_rebuild(L)]
        # Refuse a build mixing layouts before converting any of it.
        for layer in to_build:
            self._check_layout(layer, read_layout(self._source_files[layer]))

        if verbose and to_build:
            print(
                f"Building Parquet cache: {len(to_build)} of {len(candidates)} "
                f"requested layers need (re)conversion."
            )

        for i, layer in enumerate(to_build, start=1):
            self._convert_one(layer)
            if verbose and (i % 25 == 0 or i == len(to_build)):
                print(f"  [{i}/{len(to_build)}] layer {layer}")

    def _ensure_cache(self, layers: Iterable[int]) -> None:
        """Build cache only for the specific layers requested. Cheap when up-to-date."""
        self.build_cache(layers=layers, verbose=True)

    def query(
        self,
        layers: range | Iterable[int] | tuple[int, int] | None = None,
        columns: list[str] | None = None,
        x_range: tuple[float, float] | None = None,
        y_range: tuple[float, float] | None = None,
        filters: dict[str, tuple[float, float]] | None = None,
        sample_to: int | None = None,
    ) -> pl.DataFrame:
        """
        Query a slice of the dataset.

        Parameters
        ----------
        layers
            Layers to include. Accepts:
              - None: all layers
              - range: e.g. ``range(100, 201)``
              - tuple of length 2: inclusive ``(start, end)`` range
              - any other iterable of ints: an explicit set of layers
        columns
            Columns to return. ``"layer"`` and ``"Z"`` are always included
            even if not listed. If None, returns all columns.
        x_range, y_range
            Inclusive ``(min, max)`` filters on Demand X / Demand Y.
        filters
            Additional ``{column_name: (min, max)}`` inclusive filters.
        sample_to
            If set and the (filtered) result would exceed this many rows,
            downsample to roughly this many by taking an even stride during the
            scan — so the full result is never materialized. Deterministic and
            evenly spread across the selected layers. ``None`` returns every
            row. Used for plots (a scatter only draws ~150k points anyway); the
            grid never samples.

        Returns
        -------
        polars.DataFrame
        """
        layer_set = self._resolve_layers(layers)
        if not layer_set:
            raise ValueError("No layers selected by the given 'layers' argument.")

        self._ensure_cache(layer_set)

        paths = [str(self._cache_path(L)) for L in sorted(layer_set)]
        lf = pl.scan_parquet(paths, glob=False)

        # ``part_id`` is virtual (computed post-collect), not a Parquet column.
        want_part = self._parts_table is not None and (
            columns is None or "part_id" in columns
        )

        predicates: list[pl.Expr] = []
        if x_range is not None:
            lo, hi = x_range
            predicates.append(pl.col("Demand X").is_between(lo, hi))
        if y_range is not None:
            lo, hi = y_range
            predicates.append(pl.col("Demand Y").is_between(lo, hi))
        if filters:
            for col, (lo, hi) in filters.items():
                if col not in self.columns or col == "part_id":
                    raise KeyError(f"Unknown column in filters: {col!r}")
                predicates.append(pl.col(col).is_between(lo, hi))

        if predicates:
            combined = predicates[0]
            for p in predicates[1:]:
                combined = combined & p
            lf = lf.filter(combined)

        if columns is not None:
            unknown = [c for c in columns if c not in self.columns]
            if unknown:
                raise KeyError(f"Unknown column(s): {unknown}")
            keep = list(
                dict.fromkeys([*columns, "layer", "Z"])
            )  # de-dupe, preserve order
            # Scan the real columns only; part_id is attached after collect and
            # needs the coordinates present even when the caller didn't ask for
            # them.
            scan = [c for c in keep if c != "part_id"]
            if want_part:
                needs = (["Start time"] if self._parts_method == "labels"
                         else ["Demand X", "Demand Y"])
                scan = list(dict.fromkeys([*scan, *needs]))
            lf = lf.select(scan)

        # Bound memory before collect: count cheaply, then take an even stride
        # so at most ~sample_to rows are ever materialized (the full build can
        # be tens of millions of rows; a scatter only draws ~150k).
        if sample_to is not None and sample_to > 0:
            n = lf.select(pl.len()).collect().item()
            if n > sample_to:
                step = -(-n // sample_to)  # ceil(n / sample_to), >= 2 here
                lf = lf.gather_every(step)

        df = lf.collect()

        if want_part:
            if self._parts_method == "labels":
                keys = ["layer", "Start time"]
                labels = self._parts_table.select([*keys, "part_id"])
                # Only this query's layers, and keys typed like the data's.
                labels = labels.filter(
                    pl.col("layer").is_in(df["layer"].unique().to_list()))
                labels = labels.with_columns(
                    *[pl.col(k).cast(df.schema[k]) for k in keys],
                    pl.col("part_id").cast(pl.Utf8))
                df = df.join(labels, on=keys, how="left", maintain_order="left")
            elif self._parts_method == "nearest":
                from ohpal.ampm.parts import assign_nearest_part

                df = assign_nearest_part(
                    df, self._parts_table,
                    max_distance_mm=self._parts_max_dist,
                    noise_label=None, verbose=False,
                )
            else:
                from ohpal.ampm.parts import assign_bounding_box_part

                df = assign_bounding_box_part(
                    df, self._parts_table, noise_label=None, verbose=False
                )
            if columns is not None:
                keep = list(dict.fromkeys([*columns, "layer", "Z"]))
                df = df.select([c for c in keep if c in df.columns])

        return df

    def _resolve_layers(
        self,
        layers: range | Iterable[int] | tuple[int, int] | None,
    ) -> set[int]:
        """Normalize the various accepted forms into a set of available layers."""
        all_layers = set(self._source_files.keys())
        if layers is None:
            return all_layers
        if isinstance(layers, range):
            requested = set(layers)
        elif isinstance(layers, tuple) and len(layers) == 2:
            if not all(isinstance(x, numbers.Integral) for x in layers):
                raise TypeError(
                    f"Layer range tuple must be (int, int); layer numbers are "
                    f"whole numbers, got {layers!r}"
                )
            lo, hi = int(layers[0]), int(layers[1])
            requested = set(range(lo, hi + 1))
        else:
            requested = set(int(x) for x in layers)

        missing = requested - all_layers
        if missing and len(missing) == len(requested):
            raise ValueError(
                f"None of the requested layers exist. "
                f"Available range: {min(all_layers)}–{max(all_layers)}"
            )
        return requested & all_layers

    def summary(self) -> pl.DataFrame:
        """
        Per-layer summary: row count and basic ranges for spatial + key signals.
        Uses lazy scan so it doesn't load full data into memory.
        """
        self._ensure_cache(self.layers)

        paths = [str(self._cache_path(L)) for L in self.layers]
        lf = pl.scan_parquet(paths, glob=False)
        return (
            lf.group_by("layer")
            .agg(
                pl.len().alias("n_rows"),
                pl.col("Demand X").min().alias("x_min"),
                pl.col("Demand X").max().alias("x_max"),
                pl.col("Demand Y").min().alias("y_min"),
                pl.col("Demand Y").max().alias("y_max"),
            )
            .sort("layer")
            .collect()
        )

    def __repr__(self) -> str:
        L = self.layers
        return (
            f"DataStore(source_dir={self.source_dir!s}, "
            f"layers={len(L)} ({min(L)}–{max(L)}), "
            f"layer_thickness={self.layer_thickness} mm)"
        )
