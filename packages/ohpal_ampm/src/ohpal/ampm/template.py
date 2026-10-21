"""
One-call orchestration: build file (+ optional QuantAM parameters) -> template.

This is the thin wrapper a colleague invokes instead of hand-wiring the three
pieces (``BuildParts.from_dhxml`` -> ``part_parameters`` ->
``create_template(extra=...)``). It lives on the ampm side because it needs both
``ohpal.ampm`` (the parameter mapping) and ``ohpal.samples`` (the template
writer); ``ohpal.samples`` stays free of any ampm import, so the dependency
edge runs ampm -> samples -> core with no cycle.

The ``ohpal.samples`` import is deferred to call time so that importing
``ohpal.ampm`` does not eagerly pull in the samples/openpyxl stack.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import polars as pl

from ohpal.core.build import BuildParts
from ohpal.ampm.parameters import DEFAULT_PARAMETER_COLUMNS, part_parameters
from ohpal.ampm.parts import QuantAMParts

__all__ = ["make_template", "make_template_from_quant"]

log = logging.getLogger("ohpal.ampm.template")

# Shared with the dhxml template path.
_GENERATED_FILL = "D9D9D9"  # grey: generated, do not edit
_INPUT_FILL = "FFF2CC"      # yellow: fill in
_PART_WRAPPER = re.compile(r"^Part\((\d+)\)")


def make_template(
    dhxml: str | Path,
    out: str | Path,
    *,
    quant: str | Path | None = None,
    columns: tuple[str, ...] = DEFAULT_PARAMETER_COLUMNS,
    variant: str = "1",
    rename: dict[str, str] | None = None,
    tol: float = 0.0,
    build_id: str | None = None,
    **template_kwargs,
) -> Path:
    """Generate a fillable samples template from a build, optionally enriched
    with QuantAM process parameters.

    Parameters
    ----------
    dhxml
        Path to the build's ``BuildStarted.dhxml``.
    out
        Output path; ``.xlsx`` (marked/fillable) or ``.csv`` (plain).
    quant
        Optional QuantAM parts CSV. When given, its process parameters
        (position-matched to the build's parts) are appended as columns. When
        ``None``, the template carries only the build's own columns.
    columns, variant, rename, tol
        Forwarded to :func:`ohpal.ampm.parameters.part_parameters` (which
        parameters to carry, the QuantAM variant, friendlier output headers,
        and the point-in-bbox tolerance). Ignored when ``quant`` is ``None``.
    build_id
        Overrides the build id; defaults to the mtt-derived id.
    **template_kwargs
        Forwarded to ``create_template`` (e.g. ``sheet_name``,
        ``include_bounds``, ``include_alias``).

    Returns
    -------
    The path written.
    """
    build = BuildParts.from_dhxml(dhxml)

    extra = None
    if quant is not None:
        extra = part_parameters(
            quant, build, columns=columns, variant=variant, rename=rename, tol=tol
        )

    # Deferred import: keeps `import ohpal.ampm` from pulling the samples stack.
    from ohpal.samples.template import create_template

    return create_template(build, out, extra=extra, build_id=build_id, **template_kwargs)


def make_template_from_quant(
    quant: str | Path | QuantAMParts,
    out: str | Path,
    *,
    build_id: str,
    columns: tuple[str, ...] = DEFAULT_PARAMETER_COLUMNS,
    variant: str = "1",
    rename: dict[str, str] | None = None,
    include_params: bool = True,
    include_alias: bool = True,
) -> Path:
    """Reduced template for a build that has **no dhxml**, from QuantAM alone.

    Without a build file there are no bounding boxes, so this carries the part's
    **point** position (``x``/``y`` from QuantAM's ``X/Y Position``) instead of
    the six bounds, and ``part_id`` comes straight from QuantAM's ``Part ID``
    (``Part(N)`` unwrapped to ``N``; duplicates keep their ``#`` suffix). That
    id is **QuantAM-derived, not dhxml-authoritative** — if a dhxml turns up
    later, regenerate with :func:`make_template` for canonical ids and bounds.

    ``build_id`` must be supplied (a QuantAM CSV carries no mtt filename to
    derive it from). Optional process parameters are joined directly on
    ``Part ID`` (same source — no position matching needed).
    """
    qp = QuantAMParts.from_path(quant) if isinstance(quant, (str, Path)) else quant

    parent = qp.parent_parts()
    for c in ("Part ID", "X Position", "Y Position"):
        if c not in parent.columns:
            raise ValueError(f"QuantAM parent_parts missing {c!r} (have {parent.columns})")

    frame = parent.select(
        pl.lit(str(build_id)).alias("build_id"),
        pl.col("Part ID").str.replace(_PART_WRAPPER.pattern, "${1}").alias("part_id"),
        *([pl.lit(None, dtype=pl.String).alias("alias")] if include_alias else []),
        pl.col("X Position").cast(pl.Float64, strict=False).alias("x"),
        pl.col("Y Position").cast(pl.Float64, strict=False).alias("y"),
    )

    generated = {"build_id", "part_id", "x", "y"}

    if include_params:
        params = qp.volume_parameters_with_speed(variant=variant)
        missing = [c for c in columns if c not in params.columns]
        if missing:
            raise ValueError(
                f"requested columns {missing} not in QuantAM output; available: "
                f"{[c for c in params.columns if c not in ('X Position', 'Y Position')]}"
            )
        pcols = params.select(
            pl.col("Part ID").str.replace(_PART_WRAPPER.pattern, "${1}").alias("part_id"),
            *columns,
        )
        if rename:
            pcols = pcols.rename({k: v for k, v in rename.items() if k in pcols.columns})
        frame = frame.join(pcols, on="part_id", how="left")
        generated |= set(frame.columns) - {"alias"} - {"build_id", "part_id", "x", "y"}

    fills = {c: _GENERATED_FILL for c in generated}
    notes = {c: "Generated from QuantAM — do not edit." for c in generated}
    if include_alias:
        fills["alias"] = _INPUT_FILL
        notes["alias"] = "Fill in: your own name for this part."

    from ohpal.samples.writer import write_table

    # Group the positional columns into one collapsible outline.
    groups = [["x", "y"]] if {"x", "y"} <= set(frame.columns) else None
    return write_table(
        frame, out, sheet_name=str(build_id), column_fills=fills,
        column_notes=notes, column_groups=groups,
    )
