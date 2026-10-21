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

from pathlib import Path

from ohpal.core.build import BuildParts
from ohpal.ampm.parameters import DEFAULT_PARAMETER_COLUMNS, part_parameters

__all__ = ["make_template"]


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
