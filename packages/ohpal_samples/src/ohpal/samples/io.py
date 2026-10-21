"""
Tier-1 reader for hand-written characterisation workbooks.

This is the standalone-analysis surface: it turns a messy human sheet (or CSV)
into a tidy polars frame you can crunch and plot. It needs **no** build file and
**no** ``part_id`` — identity is a Tier-2 concern layered on top later.

The rules here are shaped by real workbooks (see the Archimedes density file):

* **Contiguous columns.** Starting at the first titled column, keep columns
  left-to-right until *two or more* consecutive blank headers, then stop. That
  severs the aside/pivot tables people park to the right of the main table,
  while tolerating a single untitled column mid-table.
* **Anchor row extent.** Rows are the ones where the anchor column (e.g.
  ``Cube ID``) is populated. Trailing and interior spacer rows drop out, and
  because we key on the anchor rather than row position, everything stays
  row-accurate.
* **Blank cells are nulls.** Downselected measurements are simply empty; they
  become null and never shift a row.
* **Ids stay text.** The anchor and any ``part_id`` column are kept as strings,
  so ``1+`` / ``007`` / ``name#2`` survive rather than being coerced to numbers.

Format is inferred from the extension: ``.csv``/``.tsv`` or
``.xlsx``/``.xlsm``/``.xls``.
"""

from __future__ import annotations

import re
from pathlib import Path

import polars as pl

__all__ = ["read_table", "TableReadError"]

# Headers that name a part identity column, kept as text. (Local, minimal copy
# of the matching logic in ohpal.core.identity; promote to a shared
# ohpal.core.columns helper when convenient rather than importing a private.)
_ID_HEADERS = {"partid", "part_id", "part id", "part-id"}

_EXCEL_SUFFIXES = {".xlsx", ".xlsm", ".xls", ".xltx"}
_CSV_SUFFIXES = {".csv", ".tsv"}


class TableReadError(ValueError):
    """The workbook/sheet could not be read into a tidy table."""


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _nonblank(cell: object) -> bool:
    return cell is not None and str(cell).strip() != ""


def _read_raw(source: Path, sheet: str | int | None) -> pl.DataFrame:
    """Read every cell as strings, header included as row 0, generic col names."""
    suffix = source.suffix.lower()
    if suffix in _EXCEL_SUFFIXES:
        raw = pl.read_excel(
            source,
            sheet_name=sheet if isinstance(sheet, str) else None,
            sheet_id=sheet + 1 if isinstance(sheet, int) else None,
            has_header=False,
            engine="calamine",
        )
    elif suffix in _CSV_SUFFIXES:
        raw = pl.read_csv(
            source,
            has_header=False,
            separator="\t" if suffix == ".tsv" else ",",
            infer_schema_length=0,  # all Utf8
        )
    else:
        raise TableReadError(
            f"unsupported file type {suffix!r}; expected one of "
            f"{sorted(_EXCEL_SUFFIXES | _CSV_SUFFIXES)}"
        )
    # Normalise every cell to stripped text; blanks -> null.
    return raw.select(
        pl.all()
        .cast(pl.String, strict=False)
        .str.strip_chars()
        .replace("", None)
    )


def _dedupe(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out: list[str] = []
    for n in names:
        if n in seen:
            seen[n] += 1
            out.append(f"{n}_{seen[n]}")
        else:
            seen[n] = 1
            out.append(n)
    return out


def _contiguous_block(header: tuple, max_blank: int) -> tuple[list[int], list[str]]:
    """Indices and names of the contiguous titled block in a header row."""
    start = next((i for i, h in enumerate(header) if _nonblank(h)), None)
    if start is None:
        raise TableReadError("header row is entirely blank")

    keep: list[int] = []
    names: list[str] = []
    blank_run = 0
    for i in range(start, len(header)):
        if _nonblank(header[i]):
            blank_run = 0
            keep.append(i)
            names.append(str(header[i]).strip())
        else:
            blank_run += 1
            if blank_run >= max_blank:
                break
    return keep, _dedupe(names)


def _clean_id(col: str) -> pl.Expr:
    """Keep an id column as text, but turn Excel's ``1.0`` back into ``1``."""
    c = pl.col(col)
    return (
        pl.when(c.str.contains(r"^\d+\.0+$"))
        .then(c.str.replace(r"\.0+$", ""))
        .otherwise(c)
        .alias(col)
    )


def _maybe_numeric(df: pl.DataFrame, col: str) -> pl.Series:
    """Cast a text column to Float64 only if every non-null value parses."""
    s = df[col]
    casted = s.cast(pl.Float64, strict=False)
    failures = (s.is_not_null() & casted.is_null()).sum()
    return s if failures else casted


def read_table(
    source: str | Path,
    *,
    sheet: str | int | None = None,
    header_row: int = 1,
    anchor: str = "Cube ID",
    id_columns: tuple[str, ...] = (),
    max_blank_headers: int = 2,
) -> pl.DataFrame:
    """Read one sheet/CSV into a tidy per-row frame.

    Parameters
    ----------
    source
        Path to a ``.xlsx``/``.xlsm``/``.xls`` or ``.csv``/``.tsv`` file.
    sheet
        Sheet name (str) or 0-based index (int) for workbooks; ignored for CSV.
        ``None`` takes the first sheet.
    header_row
        1-based row holding the column headers (default 1).
    anchor
        The column whose populated cells define which rows are real (default
        ``"Cube ID"``). Matched case/separator-insensitively. Kept as text.
    id_columns
        Extra columns to keep as text (beyond the anchor and any ``part_id``).
    max_blank_headers
        Consecutive blank headers that terminate the contiguous block
        (default 2, so a single untitled column is tolerated).

    Returns
    -------
    A frame with the contiguous titled columns, rows where ``anchor`` is
    populated, numeric columns inferred, and id-like columns kept as ``Utf8``.
    """
    source = Path(source)
    if not source.is_file():
        raise TableReadError(f"file not found: {source}")

    raw = _read_raw(source, sheet)
    if header_row < 1 or header_row > raw.height:
        raise TableReadError(f"header_row={header_row} out of range for {source.name}")

    header = raw.row(header_row - 1)
    keep_idx, names = _contiguous_block(header, max_blank_headers)

    body = raw.slice(header_row)
    sub = body.select(raw.columns[i] for i in keep_idx)
    sub.columns = names

    # Resolve the anchor by normalised name.
    anchor_hits = [n for n in names if _norm(n) == _norm(anchor)]
    if not anchor_hits:
        raise TableReadError(
            f"anchor column {anchor!r} not found; available columns: {names}"
        )
    anchor_col = anchor_hits[0]

    # Which columns stay text: anchor, explicit id_columns, and part_id variants.
    keep_text = {anchor_col}
    keep_text |= {n for n in names if _norm(n) in _ID_HEADERS}
    keep_text |= {n for n in names if _norm(n) in {_norm(c) for c in id_columns}}

    sub = sub.with_columns(_clean_id(c) for c in keep_text)

    # Numeric inference for everything else.
    numeric = {c: _maybe_numeric(sub, c) for c in names if c not in keep_text}
    if numeric:
        sub = sub.with_columns(**numeric)

    # Row extent: keep rows where the anchor is populated.
    return sub.filter(pl.col(anchor_col).is_not_null())
