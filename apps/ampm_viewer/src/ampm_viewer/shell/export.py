"""Export the grid to Excel — the inverse of Add-from-Excel.

Two shapes:

* **Summary** — collapse to one row per *key* (e.g. ``part_id``), with one or
  more value columns each reduced by an aggregation (``mean``, ``cov`` …). A
  value already constant within each key (a derived ``… by [part_id]`` column)
  uses ``as-is``, which is lossless.
* **Raw** — the rows as they are, a chosen subset of columns.

Pure functions over a polars frame; the caller supplies the (already shaped and
filtered) frame for the chosen scope and writes the result with ``write_xlsx``.
"""

from __future__ import annotations

from pathlib import Path

# Aggregations offered per value column. "as-is" takes the single value present
# in each key group (lossless for a column constant within the key); "cov" is
# the coefficient of variation, std / mean.
AGGS = ("as-is", "mean", "median", "std", "cov", "min", "max", "count", "sum")


def _agg_expr(col: str, reducer: str):
    import polars as pl

    c = pl.col(col)
    table = {
        "as-is": c.first(),
        "mean": c.mean(),
        "median": c.median(),
        "std": c.std(),
        "cov": (c.std() / c.mean()),
        "min": c.min(),
        "max": c.max(),
        "count": c.count(),
        "sum": c.sum(),
    }
    expr = table.get(reducer, c.first())
    name = col if reducer == "as-is" else f"{col} ({reducer})"
    return expr.alias(name)


def build_summary(df, key: str, value_aggs: list[tuple[str, str]]):
    """One row per ``key``; each (column, reducer) becomes an aggregated column.

    ``value_aggs`` is a list of (column, reducer) pairs. Rows are ordered by key.
    """
    if key not in df.columns:
        raise ValueError(f"Key column {key!r} isn't in the data.")
    pairs = [(c, r) for c, r in value_aggs if c and c in df.columns]
    if not pairs:
        raise ValueError("Pick at least one value column to aggregate.")
    exprs = [_agg_expr(c, r) for c, r in pairs]
    out = df.group_by(key, maintain_order=True).agg(exprs)
    try:
        out = out.sort(key)
    except Exception:  # noqa: BLE001 - unsortable key: leave group order
        pass
    return out


def build_raw(df, columns: list[str] | None):
    """The rows as-is, limited to ``columns`` (all of them when None/empty)."""
    if not columns:
        return df
    keep = [c for c in columns if c in df.columns]
    return df.select(keep) if keep else df


def write_xlsx(df, path: str | Path, sheet: str = "Export") -> int:
    """Write ``df`` to an .xlsx (header + rows). Returns the row count."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = (sheet or "Export")[:31]  # Excel caps sheet names at 31 chars
    ws.append(list(df.columns))
    for row in df.iter_rows():
        ws.append([_cell(v) for v in row])
    wb.save(str(path))
    return df.height


def _cell(v):
    """Coerce a polars value to something openpyxl can write."""
    if v is None:
        return None
    if isinstance(v, (int, float, str, bool)):
        return v
    return str(v)  # enums, dates, lists → text
