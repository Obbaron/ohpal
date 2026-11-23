---
title: Adding a column from Excel
section: Data
order: 40
keywords: excel, import, xlsx, spreadsheet, key, value, join, lookup, match, sheet, template, density, part_id, empty
---
# Adding a column from Excel

**Add column ▸ Excel** looks values up in a spreadsheet and adds them as a new
column, such as a density per part or an operator's rating per region.

1. **Browse…** to the workbook and choose the **sheet**.
2. Check the sheet's **key column** (what identifies a row, such as the part
   name) and its **value column** (what you want to bring in).
3. Check the table column to **match on**: the one holding the same values as
   the key column, usually `part_id`. Below it, the dialog says how many of the
   keys match on the layer shown. If none do, it says so in red and suggests
   the column that holds them, and **Run** asks before adding a column that
   would be empty.
4. Check the **new column**'s name and press **Run**.

Each choice starts on the one that is usually right, so a filled-in samples
template needs no changes:

- **Key:** a column named like `part_id` (or `Part ID`, `part`, `sample`)
  whose values the table holds, otherwise the first such column. A column
  with the same value on every row, such as `build_id`, is never the key.
- **Value:** the first column you filled in, numbers first. Columns the
  template generated (shaded grey), columns the table already has and columns
  you have already imported are passed over, so after importing a density the
  next import starts on your next measurement.
- **Match on:** the table column the keys cover best.
- **New column:** the value column's name (with a number added if it's taken).

Each row of the table gets the value whose key equals its match column. Rows
with no matching key are left empty. The status bar then says how many rows on
the layer shown got a value.

## Details

- Keys are compared as text, so `1`, `1.0` and `"1"` are the same key.
- Part names match part numbers: `Part(12)` (the table's `part_id`) and `12`
  (the `part_id` of the samples template from **New ▸ Excel template**) are
  the same part, so the template's columns, such as a density you filled in,
  can be imported on `part_id` directly.
- A key that appears twice in the sheet stops the import: remove the duplicate
  in Excel and try again.
- If every value is a number the column is numeric (usable in formulas and as
  a colour scale); otherwise it is text.
- The values are copied in. Changing the workbook later does not change the
  column; import it again to refresh it.

In a [macro](help:macros), this step asks for the file again each time the
macro runs, so the same macro can use a different workbook for each build.

To bring in the columns of the build's own parts CSV, use
[Parts ▸ Import from parts CSV](help:parts) instead.
