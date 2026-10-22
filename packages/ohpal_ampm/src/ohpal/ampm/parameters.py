"""
Per-part process parameters from a QuantAM export, keyed to the build's part_id.

This is the bridge that lets AMPM process parameters (hatch speed, laser power,
...) become columns in a samples template or the part matrix. The hard part is
*identity*: QuantAM names parts ``Part(1)``, ``Part(2)`` (deduped by a global
``Sr. No.``), while the build's ``BuildStarted.dhxml`` — and therefore
``ohpal.core`` — names them ``1``, ``2`` (deduped ``name#n``). The two suffix
schemes count different things and cannot be string-matched.

They are reconciled by **position** instead. Every part instance sits at a
unique (X, Y) on the plate (verified across real exports, including parameter
studies with hundreds of copies of one geometry), and QuantAM's
``X Position``/``Y Position`` fall inside the dhxml bounding boxes. So each
QuantAM row is matched to its build part via the point-in-bbox resolver in
``ohpal.core`` (``BuildParts.part_at``), and gets that part's canonical
``part_id``. The suffix mismatch simply never arises.

``ohpal.samples`` must not import ``ohpal.ampm``; this helper lives on the ampm
side and produces a plain ``part_id``-keyed frame that the samples template
generator consumes through its ``extra=`` seam.
"""

from __future__ import annotations

import logging
from pathlib import Path

import polars as pl

from ohpal.core.build import BuildParts, PartResolutionError
from ohpal.ampm.parts import QuantAMParts

__all__ = ["part_parameters", "ParameterMappingError", "DEFAULT_PARAMETER_COLUMNS"]

log = logging.getLogger("ohpal.ampm.parameters")

# Sensible default columns pulled from volume_parameters_with_speed. Callers can
# override; the wiring doesn't need a code change to pick a different set.
DEFAULT_PARAMETER_COLUMNS = ("Hatch Speed", "Hatches Power")

_QUANT_X = "x_center"
_QUANT_Y = "y_center"


class ParameterMappingError(ValueError):
    """A QuantAM export could not be mapped onto the build's parts."""


def part_parameters(
    quant: str | Path | QuantAMParts,
    build: BuildParts,
    *,
    columns: tuple[str, ...] = DEFAULT_PARAMETER_COLUMNS,
    variant: str = "1",
    tol: float = 0.0,
    rename: dict[str, str] | None = None,
) -> pl.DataFrame:
    """Per-part parameters keyed by the build's canonical ``part_id`` (Utf8).

    Parameters
    ----------
    quant
        A QuantAM parts CSV path or an already-loaded :class:`QuantAMParts`.
    build
        The :class:`BuildParts` for the *same* build (the identity authority).
    columns
        Parameter columns to carry through, from
        ``volume_parameters_with_speed`` (e.g. ``Hatch Speed``,
        ``Hatches Power``). Missing columns raise.
    variant
        QuantAM variant passed to ``volume_parameters_with_speed``.
    tol
        Tolerance (mm) for the point-in-bbox match; see ``BuildParts.part_at``.
    rename
        Optional map applied to the output parameter columns (e.g.
        ``{"Hatch Speed": "speed", "Hatches Power": "power"}``) for friendlier
        template headers. Keys are source column names.

    Returns
    -------
    A frame with ``part_id`` (Utf8) plus the requested parameter columns, one
    row per matched build part. Suitable for
    ``create_template(build, out, extra=...)``.

    Identity policy (per project decisions)
    ---------------------------------------
    * **Warn and keep**: a QuantAM row whose position matches no part box is a
      real anomaly (a parameter for a part not on this plate — usually a wrong
      file pairing), so it is warned about loudly and dropped from the output.
    * Build parts with no QuantAM row are simply absent here; the template's
      left-join keeps them with null parameters downstream.
    """
    qp = QuantAMParts.from_path(quant) if isinstance(quant, (str, Path)) else quant

    params = qp.volume_parameters_with_speed(variant=variant)

    for c in (_QUANT_X, _QUANT_Y):
        if c not in params.columns:
            raise ParameterMappingError(
                f"QuantAM parameters missing {c!r}; cannot position-match "
                f"(have {params.columns})"
            )
    missing = [c for c in columns if c not in params.columns]
    if missing:
        raise ParameterMappingError(
            f"requested columns {missing} not in QuantAM output; available: "
            f"{[c for c in params.columns if c not in (_QUANT_X, _QUANT_Y)]}"
        )

    # Resolve each QuantAM row to a build part_id by position (point-in-bbox).
    part_ids: list[str | None] = []
    unmatched: list[tuple] = []
    for row in params.iter_rows(named=True):
        x, y = row.get(_QUANT_X), row.get(_QUANT_Y)
        if x is None or y is None:
            part_ids.append(None)
            unmatched.append((row.get("part_id"), x, y, "missing X/Y"))
            continue
        try:
            part_ids.append(build.part_at(float(x), float(y), tol=tol))
        except PartResolutionError as e:
            part_ids.append(None)
            unmatched.append((row.get("part_id"), x, y, str(e)))

    if unmatched:
        log.warning(
            "%d QuantAM part(s) matched no build bounding box and were dropped "
            "(wrong dhxml/CSV pairing?): %s",
            len(unmatched),
            ", ".join(f"{pid!r}@({x},{y})" for pid, x, y, _ in unmatched[:10])
            + (" …" if len(unmatched) > 10 else ""),
        )

    out = (
        params.with_columns(pl.Series("part_id", part_ids, dtype=pl.String))
        .filter(pl.col("part_id").is_not_null())
        .select("part_id", *columns)
    )

    if rename:
        out = out.rename({k: v for k, v in rename.items() if k in out.columns})

    # Defensive: positions are unique, so part_id should be too. If a build has
    # genuinely overlapping boxes this would surface rather than silently dup.
    dupes = out.group_by("part_id").len().filter(pl.col("len") > 1)
    if dupes.height:
        raise ParameterMappingError(
            f"multiple QuantAM parts resolved to the same part_id "
            f"{dupes['part_id'].to_list()}; overlapping build boxes?"
        )

    return out
