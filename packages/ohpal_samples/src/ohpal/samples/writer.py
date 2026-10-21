"""
The samples output layer: write a polars frame to a fresh workbook.

Per the design, samples never edits a source workbook in place — it writes a
*fresh* file. xlsx is the default (it carries formatting and per-column marking);
CSV is the opt-in, type-lossy export. This module is used both by the template
generator and, later, by the editor's "save".

Only ever *creates* files; it does not open or mutate existing ones.
"""

from __future__ import annotations

import re
from pathlib import Path

import polars as pl
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

__all__ = ["write_xlsx", "write_csv", "write_table", "WriteError"]

_EXCEL_SUFFIXES = {".xlsx", ".xlsm", ".xltx"}
_CSV_SUFFIXES = {".csv", ".tsv"}
_INVALID_SHEET = re.compile(r"[:\\/?*\[\]]")


class WriteError(ValueError):
    """The frame could not be written."""


def _safe_sheet_name(name: str) -> str:
    return _INVALID_SHEET.sub("_", str(name))[:31] or "Sheet1"


def write_xlsx(
    frame: pl.DataFrame,
    path: str | Path,
    *,
    sheet_name: str = "Sheet1",
    font_name: str = "Arial",
    freeze_header: bool = True,
    column_fills: dict[str, str] | None = None,
    column_notes: dict[str, str] | None = None,
) -> Path:
    """Write ``frame`` to a new .xlsx with a bold header and optional per-column
    fills/notes (used to mark generated vs fill-in columns).

    ``column_fills`` maps column name -> hex colour (e.g. ``"D9D9D9"``) applied
    to that column's header and cells; ``column_notes`` maps column name -> a
    header cell comment (the legend).
    """
    path = Path(path)
    fills = {c: PatternFill("solid", fgColor=hexc) for c, hexc in (column_fills or {}).items()}
    notes = column_notes or {}
    header_font = Font(name=font_name, bold=True)
    base_font = Font(name=font_name)

    wb = Workbook()
    ws = wb.active
    ws.title = _safe_sheet_name(sheet_name)
    headers = frame.columns

    for ci, col in enumerate(headers, start=1):
        cell = ws.cell(1, ci, col)
        cell.font = header_font
        if col in fills:
            cell.fill = fills[col]
        if col in notes:
            cell.comment = Comment(notes[col], "ohpal")

    for ri, row in enumerate(frame.iter_rows(), start=2):
        for ci, (col, val) in enumerate(zip(headers, row), start=1):
            cell = ws.cell(ri, ci, val)
            cell.font = base_font
            if col in fills:
                cell.fill = fills[col]

    for ci, col in enumerate(headers, start=1):
        ws.column_dimensions[get_column_letter(ci)].width = max(10, min(30, len(str(col)) + 4))

    if freeze_header:
        ws.freeze_panes = "A2"

    wb.save(path)
    return path


def write_csv(frame: pl.DataFrame, path: str | Path, *, separator: str = ",") -> Path:
    """Write ``frame`` to a new CSV (opt-in, type-lossy export)."""
    path = Path(path)
    frame.write_csv(path, separator=separator)
    return path


def write_table(frame: pl.DataFrame, path: str | Path, **kwargs) -> Path:
    """Dispatch on extension: ``.xlsx`` -> :func:`write_xlsx`, ``.csv`` -> :func:`write_csv`.

    CSV has no formatting, so xlsx-only keyword arguments (``column_fills``,
    ``column_notes``, ``freeze_header``, ``font_name``, ``sheet_name``) are
    ignored for CSV output.
    """
    suffix = Path(path).suffix.lower()
    if suffix in _EXCEL_SUFFIXES:
        return write_xlsx(frame, path, **kwargs)
    if suffix in _CSV_SUFFIXES:
        sep = "\t" if suffix == ".tsv" else ","
        return write_csv(frame, path, separator=sep)
    raise WriteError(
        f"unsupported output type {suffix!r}; expected one of "
        f"{sorted(_EXCEL_SUFFIXES | _CSV_SUFFIXES)}"
    )
