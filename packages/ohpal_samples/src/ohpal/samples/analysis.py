"""
Tier-1 analysis over a tidy characterisation frame.

Currently: collapse replicate measurement columns into an average, standard
deviation, and count. Recomputed from the raw readings — the human's in-sheet
``Density AVG`` / ``σ`` columns are left untouched but never trusted.

The reading columns are detected, not assumed, because their count and spelling
vary by sheet: ``Density (1)..(3)``, ``Density 1..3``, ``Density (1)..(6)`` have
all been seen in one workbook. Missing replicates are simply null and skipped,
so a part measured three times and a part measured once both summarise
correctly.
"""

from __future__ import annotations

import re

import polars as pl

__all__ = [
    "summarize_readings",
    "find_reading_columns",
    "horizontal_stat",
    "canonical_stat",
    "stat_suffix",
    "VALUE_STATS",
    "STATS",
    "NoReadingColumns",
    "UnknownStat",
]


class NoReadingColumns(ValueError):
    """No replicate columns matched the given prefix."""


class UnknownStat(ValueError):
    """An unrecognised statistic name."""


# Statistic vocabulary. Users may pass any alias; output columns use the short
# suffix. VALUE_STATS carry the input's unit; ``n`` is a dimensionless count.
_ALIASES = {
    "mean": "mean", "avg": "mean", "average": "mean",
    "std": "std", "sd": "std", "stdev": "std",
    "sem": "sem", "err": "sem", "stderr": "sem",
    "sum": "sum", "min": "min", "max": "max", "median": "median",
    "n": "n", "count": "n",
}
_SUFFIX = {
    "mean": "avg", "std": "sd", "sem": "sem", "sum": "sum",
    "min": "min", "max": "max", "median": "median", "n": "n",
}
STATS = frozenset(_SUFFIX)
VALUE_STATS = frozenset({"mean", "std", "sem", "sum", "min", "max", "median"})


def canonical_stat(stat: str) -> str:
    """Resolve an alias (``avg``, ``sd``, ``err`` …) to a canonical stat name."""
    key = _ALIASES.get(stat.strip().lower())
    if key is None:
        raise UnknownStat(f"unknown statistic {stat!r}; choose from {sorted(_ALIASES)}")
    return key


def stat_suffix(stat: str) -> str:
    """Short output-column suffix for a stat (``mean`` -> ``avg``, ``std`` -> ``sd``)."""
    return _SUFFIX[canonical_stat(stat)]


def horizontal_stat(exprs: list[pl.Expr], stat: str, *, ddof: int = 1) -> pl.Expr:
    """A per-row (horizontal) reduction across ``exprs``, skipping nulls.

    The single definition of what "mean/std/sem/…​ across these columns" means,
    shared by :func:`summarize_readings`, the aggregate action, and the formula
    DSL. Empty (all-null) rows give null for value stats (0 for ``sum``, 0 for
    ``n``). ``sem`` is ``std / sqrt(n_non_null)``.
    """
    kind = canonical_stat(stat)
    lst = pl.concat_list([e.cast(pl.Float64, strict=False) for e in exprs])
    if kind == "mean":
        return lst.list.mean()
    if kind == "sum":
        return lst.list.sum()
    if kind == "min":
        return lst.list.min()
    if kind == "max":
        return lst.list.max()
    if kind == "median":
        return lst.list.median()
    if kind == "std":
        return lst.list.std(ddof=ddof)
    if kind == "sem":
        n = lst.list.drop_nulls().list.len().cast(pl.Float64)
        return lst.list.std(ddof=ddof) / n.sqrt()
    # n
    return lst.list.drop_nulls().list.len().cast(pl.Int32)


def find_reading_columns(df: pl.DataFrame, prefix: str) -> list[str]:
    """Columns like ``<prefix> 1`` / ``<prefix> (1)``, ordered by their number.

    Matching is case-insensitive and ignores spacing and parentheses, so
    ``Density 1``, ``Density (1)`` and ``density1`` all count.
    """
    pat = re.compile(rf"^{re.escape(prefix)}\s*\(?\s*(\d+)\s*\)?$", re.IGNORECASE)
    numbered: list[tuple[int, str]] = []
    for col in df.columns:
        m = pat.match(col.strip())
        if m:
            numbered.append((int(m.group(1)), col))
    return [col for _, col in sorted(numbered)]


def summarize_readings(
    df: pl.DataFrame,
    *,
    prefix: str = "Density",
    out_prefix: str | None = None,
    ddof: int = 1,
) -> pl.DataFrame:
    """Add ``<out>_avg`` / ``<out>_sd`` / ``<out>_n`` from replicate columns.

    Parameters
    ----------
    prefix
        Header stem of the replicate columns (default ``"Density"``).
    out_prefix
        Stem for the output columns; defaults to ``prefix`` lowercased with
        non-alphanumerics collapsed to ``_`` (so ``"Density"`` -> ``density``).
    ddof
        Delta degrees of freedom for the SD (default 1 = sample SD). A part with
        a single reading gets a null SD; zero readings gets null avg and SD.

    Raises
    ------
    NoReadingColumns
        If no column matches ``prefix``.
    """
    cols = find_reading_columns(df, prefix)
    if not cols:
        raise NoReadingColumns(
            f"no reading columns match prefix {prefix!r}; columns are {df.columns}"
        )

    out = out_prefix or re.sub(r"[^a-z0-9]+", "_", prefix.lower()).strip("_")
    exprs = [pl.col(c) for c in cols]

    return df.with_columns(
        horizontal_stat(exprs, "mean").alias(f"{out}_avg"),
        horizontal_stat(exprs, "std", ddof=ddof).alias(f"{out}_sd"),
        horizontal_stat(exprs, "n").alias(f"{out}_n"),
    )
