"""
Generate the initial samples workbook from a build.

This is the tool that seeds a workbook with the machine's ``part_id`` at
data-entry time — the thing that makes identity tractable downstream, because
the human never has to reproduce the machine's part naming by hand.

The generated sheet carries the authoritative keys and coordinates (from the
build's ``BuildStarted.dhxml`` via :class:`ohpal.core.build.BuildParts`), plus
an empty ``alias`` column for the human's own name for each part. Generated
columns are shaded grey ("do not edit"); the fill-in column is shaded yellow.
The human adds their measurement columns to the right and records the readings.

Build parameters (speed/power) are intentionally *not* sourced here — they live
in ``ohpal.ampm`` and this package must not depend on it. The ``extra`` seam
lets a caller pass in any per-part frame (keyed by ``part_id``) to append as
further generated columns, so the capability exists without the coupling.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from ohpal.core.build import BuildParts
from ohpal.samples.writer import write_table

__all__ = ["build_template_frame", "create_template", "create_template_from_dhxml"]

_GENERATED_FILL = "D9D9D9"  # grey: generated from the build, do not edit
_INPUT_FILL = "FFF2CC"      # light yellow: fill this in

_ALIAS = "alias"


def _resolve_build_id(build: BuildParts, build_id: str | None) -> str:
    bid = build_id if build_id is not None else build.build_id
    if not bid:
        raise ValueError(
            "no build_id: none supplied and the build file has no mtt filename "
            "or name; pass build_id= explicitly"
        )
    return bid
_BOUNDS = ("x_min", "x_max", "y_min", "y_max", "z_min", "z_max")


def build_template_frame(
    build: BuildParts,
    *,
    build_id: str | None = None,
    include_bounds: bool = True,
    include_alias: bool = True,
    extra: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Assemble the starter per-part frame: one row per build part.

    Always ``build_id`` + ``part_id``; optionally an empty ``alias`` column,
    the part's XYZ bounding-box bounds, and any ``extra`` per-part columns joined on
    ``part_id``. ``build_id`` defaults to the build's mtt-derived id.
    """
    build_id = _resolve_build_id(build, build_id)
    pt = build.parts_table()

    cols: list[pl.Expr] = [pl.lit(build_id).alias("build_id"), pl.col("part_id")]
    if include_alias:
        cols.append(pl.lit(None, dtype=pl.String).alias(_ALIAS))
    if include_bounds:
        cols += [pl.col(c) for c in _BOUNDS]
    frame = pt.select(cols)

    if extra is not None:
        if "part_id" not in extra.columns:
            raise ValueError("extra frame must carry a 'part_id' column to join on")
        frame = frame.join(extra, on="part_id", how="left")

    return frame


def _marking(
    frame: pl.DataFrame,
    *,
    include_bounds: bool,
    include_alias: bool,
    extra: pl.DataFrame | None,
) -> tuple[dict[str, str], dict[str, str]]:
    generated = {"build_id", "part_id"}
    if include_bounds:
        generated |= set(_BOUNDS)
    if extra is not None:
        generated |= set(extra.columns) - {"part_id"}
    inputs = {_ALIAS} if include_alias else set()

    fills = {c: _GENERATED_FILL for c in generated}
    fills.update({c: _INPUT_FILL for c in inputs})
    notes = {c: "Generated from build — do not edit." for c in generated}
    notes.update({c: "Fill in: your own name for this part." for c in inputs})
    return fills, notes


def create_template(
    build: BuildParts,
    path: str | Path,
    *,
    build_id: str | None = None,
    sheet_name: str | None = None,
    include_bounds: bool = True,
    include_alias: bool = True,
    extra: pl.DataFrame | None = None,
) -> Path:
    """Generate a fillable workbook (or CSV) for ``build`` at ``path``.

    ``build_id`` defaults to the build's mtt-derived id. The sheet defaults to
    being named after ``build_id``. Output format follows the ``path`` extension
    (``.xlsx`` gets the column marking; ``.csv`` is plain).
    """
    build_id = _resolve_build_id(build, build_id)
    frame = build_template_frame(
        build,
        build_id=build_id,
        include_bounds=include_bounds,
        include_alias=include_alias,
        extra=extra,
    )
    fills, notes = _marking(
        frame,
        include_bounds=include_bounds,
        include_alias=include_alias,
        extra=extra,
    )
    # Group the six bound columns into one collapsible outline.
    groups = [list(_BOUNDS)] if include_bounds else None
    return write_table(
        frame,
        path,
        sheet_name=sheet_name or str(build_id),
        column_fills=fills,
        column_notes=notes,
        column_groups=groups,
    )


def create_template_from_dhxml(
    dhxml_path: str | Path,
    path: str | Path,
    *,
    build_id: str | None = None,
    **kwargs,
) -> Path:
    """Convenience: read the build file and generate the template in one call."""
    return create_template(BuildParts.from_dhxml(dhxml_path), path, build_id=build_id, **kwargs)
