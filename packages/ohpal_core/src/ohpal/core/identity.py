"""
Resolving a per-part table to the canonical ``part_id`` join key.

A characterisation sheet arrives keyed by whatever the human used — often an
alias like ``Cube ID`` that is deliberately *unrelated* to the machine's
``part_id``. This module adds the canonical key so the table can join the part
matrix. It never needs to happen for standalone analysis (Tier 1); it is only
required for the cross-package provider role (Tier 2).

Design
------
A :class:`PartIdentityResolver` answers two questions: is it *applicable* to a
given frame, and if so, *resolve* it (add ``part_id`` as ``Utf8``). Resolvers
are tried in order by :func:`resolve_part_id`, and the rule is
**first-applicable owns its failures**: the first resolver whose ``applicable``
returns True is the one used, and its errors propagate as hard failures rather
than silently falling through to the next resolver. This keeps a real ambiguity
(two overlapping part boxes, a part_id column with holes) from being masked by a
weaker fallback.

Two resolvers live here because they depend only on ``ohpal.core.build``:

  * :class:`DirectColumnResolver` — the sheet already carries a part_id column.
  * :class:`SpatialBBoxResolver`  — the sheet carries x/y[/z] origins, matched
    into the build's bounding boxes.

The heavier ``AmpmClusterResolver`` (reconstruct identity from monitoring
clusters) depends on ``ohpal.ampm`` and therefore lives *there*; it implements
this module's protocol and is appended to the chain by the orchestrator, so
core never imports ampm. See ``tests/test_identity.py`` for the conformance
seam that proves an external resolver slots in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import polars as pl

from ohpal.core.build import BuildParts

__all__ = [
    "PART_ID",
    "PartIdentityResolver",
    "DirectColumnResolver",
    "SpatialBBoxResolver",
    "default_resolvers",
    "resolve_part_id",
    "IdentityError",
    "NoApplicableResolver",
    "AmbiguousColumn",
    "DuplicatePartId",
]

# Canonical join key. (Will move to the ohpal.core.parts contract module when
# the provider/merge layer lands; kept here for now as the single spelling.)
PART_ID = "part_id"


class IdentityError(ValueError):
    """Base for identity-resolution failures."""


class NoApplicableResolver(IdentityError):
    """No resolver in the chain could handle the frame."""


class AmbiguousColumn(IdentityError):
    """More than one column matched a role (e.g. two 'part id' columns)."""


class DuplicatePartId(IdentityError):
    """Resolution produced a non-unique key, which cannot join cleanly."""


# ---- column name matching -------------------------------------------------

def _normalize(name: str) -> str:
    """Fold a header to a comparison form: lowercase, alphanumerics only.

    So ``"Part ID"``, ``"part_id"``, ``"part-id"`` and ``"partid"`` all collapse
    to ``"partid"`` — while ``"Cube ID"`` collapses to ``"cubeid"`` and never
    collides with the part_id role.
    """
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _find_column(df: pl.DataFrame, candidates: tuple[str, ...], role: str) -> str | None:
    """Return the single df column matching any candidate, or None.

    Raises :class:`AmbiguousColumn` if more than one column matches — better to
    stop than to guess which 'part id' column the human meant.
    """
    wanted = {_normalize(c) for c in candidates}
    hits = [c for c in df.columns if _normalize(c) in wanted]

    if len(hits) > 1:
        raise AmbiguousColumn(
            f"{role}: multiple columns match {sorted(hits)}; rename so only one "
            f"is the {role} column"
        )
    return hits[0] if hits else None


# Default header variants. Case/separator-insensitive via _normalize, so e.g.
# "part id" already covers "Part ID", "PART_ID", "part-id".
_PART_ID_CANDIDATES = ("part_id", "part id", "partid", "part-id")
_X_CANDIDATES = ("x", "x position", "x pos", "origin x", "x origin", "x (mm)")
_Y_CANDIDATES = ("y", "y position", "y pos", "origin y", "y origin", "y (mm)")
_Z_CANDIDATES = ("z", "z position", "z pos", "origin z", "z origin", "z (mm)")


# ---- resolver protocol ----------------------------------------------------

@runtime_checkable
class PartIdentityResolver(Protocol):
    """Adds a canonical ``part_id`` (Utf8) to a per-part frame.

    Implementations must be side-effect free and return a *new* frame. An
    applicable resolver that then hits trouble must raise, not return a frame
    without ``part_id``.
    """

    name: str

    def applicable(self, df: pl.DataFrame) -> bool: ...

    def resolve(self, df: pl.DataFrame) -> pl.DataFrame: ...


# ---- concrete resolvers ---------------------------------------------------

@dataclass(frozen=True)
class DirectColumnResolver:
    """The sheet already carries a part_id column; normalise it to the key.

    Applicable when a part_id-variant column exists *and* has at least one
    non-null value. A header that exists but is entirely empty is treated as
    absent, so resolution can fall through to a spatial resolver. A column that
    is *partially* filled is a hard error — the chain resolves a whole frame
    with one resolver, so a part_id column with holes is a mistake to surface,
    not something to silently patch from coordinates.
    """

    name: str = "direct"
    candidates: tuple[str, ...] = _PART_ID_CANDIDATES

    def _match(self, df: pl.DataFrame) -> str | None:
        return _find_column(df, self.candidates, role="part_id")

    def applicable(self, df: pl.DataFrame) -> bool:
        col = self._match(df)
        if col is None:
            return False
        # Entirely-empty column counts as "no part_id column".
        return df[col].null_count() < df.height

    def resolve(self, df: pl.DataFrame) -> pl.DataFrame:
        col = self._match(df)
        if col is None:  # pragma: no cover - guarded by applicable()
            raise NoApplicableResolver("no part_id column")

        null_rows = df[col].null_count()
        if null_rows:
            raise IdentityError(
                f"part_id column {col!r} has {null_rows} empty cell(s); every "
                f"part row needs a key (or drop the column to use coordinates)"
            )

        out = df
        if col != PART_ID:
            out = out.rename({col: PART_ID})
        # Cast last so leading-zero / suffixed ids survive as text.
        return out.with_columns(pl.col(PART_ID).cast(pl.String))


@dataclass(frozen=True)
class SpatialBBoxResolver:
    """The sheet carries x/y[/z] origins; match them into the build's boxes.

    Wraps :meth:`BuildParts.part_ids_at`, inheriting its strict policy: each
    origin must fall in exactly one part box (or a unique nearest within
    ``tol``); zero or ambiguous matches raise. ``z`` is degenerate on typical
    builds, so matching is 2D unless ``use_z`` is set.
    """

    build: BuildParts
    name: str = "spatial"
    tol: float = 0.0
    use_z: bool = False
    x_candidates: tuple[str, ...] = _X_CANDIDATES
    y_candidates: tuple[str, ...] = _Y_CANDIDATES
    z_candidates: tuple[str, ...] = _Z_CANDIDATES

    def _axes(self, df: pl.DataFrame) -> tuple[str | None, str | None, str | None]:
        x = _find_column(df, self.x_candidates, role="x")
        y = _find_column(df, self.y_candidates, role="y")
        z = _find_column(df, self.z_candidates, role="z") if self.use_z else None
        return x, y, z

    def applicable(self, df: pl.DataFrame) -> bool:
        x, y, z = self._axes(df)
        if x is None or y is None:
            return False
        if self.use_z and z is None:
            return False
        return True

    def resolve(self, df: pl.DataFrame) -> pl.DataFrame:
        x, y, z = self._axes(df)
        if x is None or y is None or (self.use_z and z is None):  # pragma: no cover
            raise NoApplicableResolver("missing coordinate column(s)")

        return self.build.part_ids_at(
            df,
            x_col=x,
            y_col=y,
            z_col=z or "z",
            use_z=self.use_z,
            tol=self.tol,
            out_col=PART_ID,
        )


def default_resolvers(build: BuildParts | None = None) -> list[PartIdentityResolver]:
    """The recommended chain: prefer an existing part_id column, then spatial.

    ``build`` is required for the spatial link; omit it (or pass None) for
    direct-only resolution.
    """
    chain: list[PartIdentityResolver] = [DirectColumnResolver()]
    if build is not None:
        chain.append(SpatialBBoxResolver(build))
    return chain


# ---- chain runner ---------------------------------------------------------

def resolve_part_id(
    df: pl.DataFrame,
    resolvers: list[PartIdentityResolver],
    *,
    require_unique: bool = False,
) -> pl.DataFrame:
    """Add canonical ``part_id`` using the first applicable resolver.

    First-applicable-owns-failures: the first resolver whose ``applicable``
    returns True is used, and its errors propagate. If none apply, raises
    :class:`NoApplicableResolver`.

    Guarantees on return: a ``part_id`` column exists, is ``Utf8``, and has no
    nulls. With ``require_unique=True``, also raises :class:`DuplicatePartId`
    if the key is not unique across rows (needed before joining the matrix).
    """
    chosen = None
    for r in resolvers:
        if r.applicable(df):
            chosen = r
            break

    if chosen is None:
        tried = ", ".join(r.name for r in resolvers) or "(none)"
        raise NoApplicableResolver(
            f"no resolver applies to columns {df.columns}; tried: {tried}"
        )

    out = chosen.resolve(df)

    if PART_ID not in out.columns:
        raise IdentityError(f"resolver {chosen.name!r} returned no {PART_ID!r} column")
    out = out.with_columns(pl.col(PART_ID).cast(pl.String))
    if out[PART_ID].null_count():
        raise IdentityError(f"resolver {chosen.name!r} left null {PART_ID} values")

    if require_unique:
        dupes = (
            out.group_by(PART_ID)
            .len()
            .filter(pl.col("len") > 1)[PART_ID]
            .to_list()
        )
        if dupes:
            raise DuplicatePartId(
                f"{chosen.name!r} produced duplicate part_id(s) {sorted(dupes)}; "
                f"the join key must be unique per part"
            )

    return out
