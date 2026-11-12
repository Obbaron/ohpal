---
title: Adding a column from Excel
section: Data
order: 40
keywords: excel, import, xlsx, spreadsheet, key, value, join, lookup, match, sheet
---
# Adding a column from Excel

**Add column ▸ Excel** looks values up in a spreadsheet and adds them as a new
column, such as a density per part or an operator's rating per region.

1. **Browse…** to the workbook and choose the **sheet**.
2. Choose the sheet's **key column** (what identifies a row, such as the part
   name) and its **value column** (what you want to bring in).
3. Choose the table column to **match on**, usually `part_id`.
4. Name the **new column** and confirm.

Each row of the table gets the value whose key equals its match column. Rows
with no matching key are left empty.

## Details

- Keys are compared as text, so `1`, `1.0` and `"1"` are the same key.
- A key that appears twice in the sheet stops the import: remove the duplicate
  in Excel and try again.
- If every value is a number the column is numeric (usable in formulas and as
  a colour scale); otherwise it is text.
- The values are copied in. Changing the workbook later does not change the
  column; import it again to refresh it.

In a [macro](help:macros), this step asks for the file again each time the
macro runs, so the same macro can use a different workbook for each build.

To bring in the columns of the build's own parts CSV, use
[Parts ▸ Import parts CSV](help:parts) instead.
