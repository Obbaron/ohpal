"""
The cross-package part-attribute contract and the frame merger.

Both ``ohpal.samples`` and ``ohpal.ampm`` produce the same *shape* of thing: a
per-part table keyed by ``part_id`` (and optionally ``build_id``), where each
package contributes some attribute columns. "Interop" is just joining those
tables on the key. This module owns that contract:

  * :class:`PartAttributeProvider` — the protocol a package implements to
    contribute columns.
  * :func:`namespace_columns` — the collision-proof ``provider__column``
    prefixing that also encodes provenance.
  * :func:`merge` — the pure outer-join over already-materialised provider
    frames.

What this module deliberately does *not* do yet is *discovery*: finding
providers via entry-points, constructing them from a context, running a
selected/lazy subset. That layer sits on top of :func:`merge` and is added once
the ``ProviderContext`` shape is settled. :func:`merge` is the dumb, total join
that every test and both providers need first.

Key model
---------
The canonical key is ``(build_id, part_id)``. ``build_id`` is *optional*: if
frames carry it, it participates in the key; if no frame carries it, ``merge``
runs in single-build mode on ``part_id`` alone. Mixing (some frames with
``build_id``, some without) is rejected as ambiguous.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import polars as pl

from ohpal.core.identity import PART_ID

__all__ = [
    "PART_ID",
    "BUILD_ID",
    "NAMESPACE_SEP",
    "PartAttributeProvider",
    "namespace_columns",
    "attribute_columns",
    "merge",
    "MergeError",
]

BUILD_ID = "build_id"
NAMESPACE_SEP = "__"

# Columns that are keys, not attributes — never prefixed, always joined on.
_KEY_COLS = (BUILD_ID, PART_ID)


class MergeError(ValueError):
    """A provider frame violates the merge contract."""


@runtime_checkable
class PartAttributeProvider(Protocol):
    """A source of per-part attribute columns.

    ``name`` doubles as the column prefix and the provenance tag. ``provide``
    returns a per-part frame carrying the key column(s) plus this provider's
    attributes; attributes should already be namespaced ``{name}__{col}`` (use
    :func:`namespace_columns`). Returning a ``LazyFrame`` lets the caller defer
    expensive work — :func:`merge` collects as needed.
    """

    name: str

    def provide(self, build_id: str) -> pl.LazyFrame: ...


def attribute_columns(df: pl.DataFrame) -> list[str]:
    """The non-key columns of a per-part frame."""
    return [c for c in df.columns if c not in _KEY_COLS]


def namespace_columns(df: pl.DataFrame, provider: str) -> pl.DataFrame:
    """Prefix every attribute column with ``{provider}__``.

    Key columns (``build_id``, ``part_id``) are left untouched. Columns already
    carrying *this* provider's prefix are left as-is (idempotent), so a provider
    can call this safely regardless of whether it pre-namespaced.
    """
    prefix = f"{provider}{NAMESPACE_SEP}"
    rename = {
        c: f"{prefix}{c}"
        for c in attribute_columns(df)
        if not c.startswith(prefix)
    }
    return df.rename(rename) if rename else df


def _resolve_key(frames: list[pl.DataFrame]) -> list[str]:
    """Decide the join key and validate build_id consistency across frames."""
    has_build = [BUILD_ID in f.columns for f in frames]

    if all(has_build):
        return [BUILD_ID, PART_ID]
    if not any(has_build):
        return [PART_ID]

    with_ = [i for i, h in enumerate(has_build) if h]
    without = [i for i, h in enumerate(has_build) if not h]
    raise MergeError(
        f"mixed build_id: frames {with_} carry {BUILD_ID!r} but {without} do "
        f"not. Either every frame carries build_id (multi-build) or none do "
        f"(single-build)."
    )


def _check_frame(df: pl.DataFrame, key: list[str], idx: int) -> None:
    for k in key:
        if k not in df.columns:
            raise MergeError(f"frame {idx} is missing key column {k!r}")
    if df[PART_ID].dtype != pl.String:
        raise MergeError(
            f"frame {idx}: {PART_ID!r} must be Utf8, got {df[PART_ID].dtype}"
        )
    if df[PART_ID].null_count():
        raise MergeError(f"frame {idx}: {PART_ID!r} has null values")
    dupes = df.group_by(key).len().filter(pl.col("len") > 1)
    if dupes.height:
        raise MergeError(
            f"frame {idx}: duplicate key(s) {dupes.drop('len').rows()}; each "
            f"part must appear once per frame"
        )


def merge(
    frames: list[pl.DataFrame],
    *,
    how: str = "outer",
) -> pl.DataFrame:
    """Join per-part frames on the canonical key into one wide part matrix.

    Parameters
    ----------
    frames
        Already-materialised per-part frames, each carrying the key column(s)
        plus namespaced attribute columns. Namespacing is the provider's
        responsibility; ``merge`` verifies there are no attribute-name
        collisions across frames and does **not** silently re-prefix.
    how
        Join strategy: ``"outer"`` (default — keep all parts from all frames,
        null-filling gaps), ``"inner"`` (only parts every frame covers), or
        ``"left"`` (parts in the first frame).

    Raises
    ------
    MergeError
        On a missing/duplicate/mistyped key, mixed build_id presence, or an
        attribute-column collision between frames.
    """
    if not frames:
        raise MergeError("merge() needs at least one frame")
    if how not in ("outer", "inner", "left"):
        raise MergeError(f"unknown join strategy {how!r}")

    # Public API uses the SQL term "outer"; polars spells it "full".
    pl_how = {"outer": "full", "inner": "inner", "left": "left"}[how]

    key = _resolve_key(frames)
    for i, f in enumerate(frames):
        _check_frame(f, key, i)

    # Reject attribute-name collisions before joining — clearer than a suffix
    # surprise, and enforces that providers namespace their columns.
    seen: dict[str, int] = {}
    for i, f in enumerate(frames):
        for c in attribute_columns(f):
            if c in seen:
                raise MergeError(
                    f"attribute column {c!r} appears in frames {seen[c]} and "
                    f"{i}; providers must namespace their columns "
                    f"(e.g. samples{NAMESPACE_SEP}{c})"
                )
            seen[c] = i

    out = frames[0]
    for f in frames[1:]:
        # coalesce=True keeps a single key column rather than key_right dupes.
        out = out.join(f, on=key, how=pl_how, coalesce=True)

    return out.sort(key)
