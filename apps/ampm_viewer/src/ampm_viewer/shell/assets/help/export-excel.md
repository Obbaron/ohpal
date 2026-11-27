---
title: Exporting to Excel
section: Data
order: 70
keywords: export, excel, xlsx, summary, raw, save, key, aggregate, scope, sheet, table, every row, all rows, sample, too many rows, limit
---
# Exporting to Excel

**Export to Excel** on the Data toolbar writes the data, as you have shaped
it, to a workbook.

## Summary or raw

- **Summary (one row per key)**: a compact table. Choose the **key** (one row
  per part, per layer, per label…) and one or more **values**, each with how
  to reduce it: mean, median, std, CoV, min, max, count or sum. **+ Add
  value** adds another column.

  Choose **as-is** for a value that is already one number per key, such as a
  CoV you calculated `by [part_id]`.
- **Raw rows**: the rows themselves. Tick the **columns to include**.

## Scope

- **Current view**: the layer on screen.
- **All layers**: the whole build.
- **Range**: the layers you set.

An export uses every row of its layers. (Plots draw from up to 1,000,000 rows
spread evenly through a big build; an export doesn't sample, so its numbers
are the data's.) Only the columns the export needs are read, so a summary of
a whole build fits in memory, though a large build takes a while.

Tick **Respect the active row filters** to export only the rows that pass the
[filters](help:filters).

## Output

**Save as…** chooses the file, and **Sheet** names the worksheet. Press
**Export**; the status bar reports when the file has been written.

Exporting many layers of raw rows makes a large file and takes a moment.
An Excel sheet holds 1,048,576 rows, the header included: a raw export with
more rows isn't written, and the status bar says so. Export a range of
layers, filter the rows, or export a summary instead.

## In a macro

An export is recorded as *what* to write, never *where*. When the macro runs
it asks where to save each file before it starts. See [Macros](help:macros).

To create the samples-template workbook for a build instead, see
[Excel template](help:create-excel).
