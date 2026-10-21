"""Tests for ohpal.samples.io.read_table."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from openpyxl import Workbook

from ohpal.samples.io import TableReadError, read_table

REAL = Path("/mnt/user-data/uploads/Archimedes_Density_TiAg.xlsx")


def _xlsx(tmp_path: Path, main: list[list], *, side_at: int | None = None,
          side: list[list] | None = None, name="book.xlsx") -> Path:
    """Write a main table at A1; optionally a side table starting at 0-based
    column ``side_at`` (leaving the gap the caller builds into that offset)."""
    wb = Workbook()
    ws = wb.active
    for r, row in enumerate(main, start=1):
        for c, val in enumerate(row, start=1):
            if val is not None:
                ws.cell(row=r, column=c, value=val)
    if side is not None and side_at is not None:
        for r, row in enumerate(side, start=1):
            for c, val in enumerate(row, start=1):
                if val is not None:
                    ws.cell(row=r, column=side_at + c, value=val)
    p = tmp_path / name
    wb.save(p)
    return p


# ---- CSV basics -----------------------------------------------------------

def test_csv_reads_and_filters_by_anchor(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text("Cube ID,density\n1,4.5\n2,4.4\n\n,\n", encoding="utf-8")
    df = read_table(p)
    assert df["Cube ID"].to_list() == ["1", "2"]      # blank-anchor rows dropped
    assert df.schema["Cube ID"] == pl.String
    assert df.schema["density"] == pl.Float64          # numeric inferred


def test_unsupported_extension_raises(tmp_path):
    p = tmp_path / "d.parquet"
    p.write_bytes(b"x")
    with pytest.raises(TableReadError, match="unsupported"):
        read_table(p)


def test_missing_file_raises(tmp_path):
    with pytest.raises(TableReadError, match="not found"):
        read_table(tmp_path / "nope.csv")


# ---- contiguous-column rule ----------------------------------------------

def test_side_table_severed_by_two_blank_headers(tmp_path):
    # main occupies cols 1-3 (A-C), gap at D-E, side table from F.
    main = [["Cube ID", "Speed", "density"],
            [1, 200, 4.5],
            [2, 210, 4.4]]
    side = [["Row", "x", "y"], [1, 9, 9], [2, 8, 8]]
    p = _xlsx(tmp_path, main, side_at=5, side=side)  # side starts at col F (index 5)
    df = read_table(p)
    assert df.columns == ["Cube ID", "Speed", "density"]   # side table excluded
    assert df.height == 2


def test_single_blank_header_tolerated(tmp_path):
    # one untitled column (D) between titled columns -> block continues, untitled dropped
    main = [["Cube ID", "Speed", None, "density"],
            [1, 200, "junk", 4.5],
            [2, 210, "junk", 4.4]]
    p = _xlsx(tmp_path, main)
    df = read_table(p)
    assert df.columns == ["Cube ID", "Speed", "density"]
    assert df.height == 2


# ---- id fidelity ----------------------------------------------------------

def test_suffixed_ids_stay_text(tmp_path):
    main = [["Cube ID", "density"], [1, 4.5], ["1+", 4.4], ["2+", 4.3]]
    p = _xlsx(tmp_path, main)
    df = read_table(p)
    assert df["Cube ID"].to_list() == ["1", "1+", "2+"]
    assert df.schema["Cube ID"] == pl.String


def test_numeric_id_not_rendered_as_float(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text("Cube ID,density\n1,4.5\n2,4.4\n", encoding="utf-8")
    df = read_table(p)
    assert df["Cube ID"].to_list() == ["1", "2"]  # not "1.0"


def test_part_id_column_kept_as_text(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text("Cube ID,part_id,density\n1,007,4.5\n", encoding="utf-8")
    df = read_table(p)
    assert df.schema["part_id"] == pl.String
    assert df["part_id"].to_list() == ["007"]


# ---- anchor / header handling --------------------------------------------

def test_anchor_not_found_raises(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text("Widget,density\n1,4.5\n", encoding="utf-8")
    with pytest.raises(TableReadError, match="anchor column"):
        read_table(p)  # default anchor 'Cube ID' absent


def test_custom_anchor(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text("Sample,density\nA,4.5\n,4.4\nB,4.3\n", encoding="utf-8")
    df = read_table(p, anchor="Sample")
    assert df["Sample"].to_list() == ["A", "B"]  # middle blank-anchor row dropped


def test_anchor_case_insensitive(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text("cube_id,density\n1,4.5\n", encoding="utf-8")
    df = read_table(p, anchor="Cube ID")
    assert df.height == 1


def test_interior_blank_row_dropped_row_accurately(tmp_path):
    main = [["Cube ID", "density"], [1, 4.5], [None, None], [3, 4.3]]
    p = _xlsx(tmp_path, main)
    df = read_table(p)
    assert df["Cube ID"].to_list() == ["1", "3"]
    assert df["density"].to_list() == [4.5, 4.3]  # stays aligned


# ---- real workbook smoke --------------------------------------------------

@pytest.mark.skipif(not REAL.exists(), reason="sample workbook not present")
def test_real_ti15ag_excludes_side_table():
    df = read_table(REAL, sheet="Ti-15Ag")
    assert "Row" in df.columns  # the *main* Row/Column, kept
    # side table (second 'Row' + numeric headers) excluded -> 12 columns
    assert df.width == 12
    assert df["Cube ID"].to_list()[-1] == "8+"  # human suffix preserved
