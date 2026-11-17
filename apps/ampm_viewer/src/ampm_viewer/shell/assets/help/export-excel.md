---
title: Exporting to Excel
section: Data
order: 70
keywords: export, excel, xlsx, summary, raw, save, key, aggregate, scope, sheet, table
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

Tick **Respect the active row filters** to export only the rows that pass the
[filters](help:filters).

## Output

**Save as…** chooses the file, and **Sheet** names the worksheet. Press
**Export**; the status bar reports when the file has been written.

Exporting many layers of raw rows makes a large file and takes a moment.
Excel itself stops at about a million rows per sheet, so prefer a summary for
whole-build exports.

## In a macro

An export is recorded as *what* to write, never *where*. When the macro runs
it asks where to save each file before it starts. See [Macros](help:macros).

To create the samples-template workbook for a build instead, see
[Create Excel from AMPM](help:create-excel).
