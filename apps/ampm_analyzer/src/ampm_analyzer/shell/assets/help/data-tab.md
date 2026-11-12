---
title: The Data tab
section: Data
order: 10
keywords: data, grid, table, layer, columns, header, select, reorder, resize, panel, sig figs, significant figures, column info, hide, show
context: data
---
# The Data tab

The Data tab shows the build as a table: one row per measured point, one layer
at a time. It is where you prepare the data that plots and exports use.

## Moving between layers

The **Layer** box on the toolbar chooses the layer on screen. It only stops on
layers that have data. Layers that were not built, or that the mask emptied,
are skipped. The status bar shows how many rows the layer has.

The table shows one layer, but the changes you make here (new columns,
filters, renames) apply to every layer and to every plot.

## Working with columns

- **Select** a column by clicking its header. Ctrl-click or Shift-click selects
  several. **Reset selection** on the toolbar clears it.
- **Reorder** by dragging a header; a line shows where it will land.
- **Resize** by dragging a header's edge. A name too long for its column shows
  its end (`…ches Power`), since that is usually the part that differs.
- **Show or hide** columns from the **Show/hide columns** menu. The menu stays
  open so you can tick several. Hiding only tidies the view; the column is
  still there for formulas and plots.
- **Rename** by double-clicking a header, or select the column and use
  **Rename column**. Formulas, filters and open plots that use the column
  follow the new name.

Order, widths and hidden columns are remembered for each build.

## Column details

Double-click any cell to open that column in the side panel. It shows the
column's name (editable), how many rows it has and how many are empty, and its
type. For decimal columns, **Sig figs** sets how many significant figures the
table displays; it changes the display only, never the values.

While the panel is open it follows the column you select.

## What else you can do here

| To… | See |
| --- | --- |
| Add a calculated column | [Calculated columns](help:columns-calculation) |
| Tag rows with a label | [Label columns](help:columns-label) |
| Bring in values from a spreadsheet | [Adding a column from Excel](help:columns-excel) |
| Remove or restore columns | [Renaming, removing and restoring columns](help:columns-manage) |
| Work per part | [Parts](help:parts) |
| Narrow the rows | [Filters](help:filters) |
| Make a plot | [Creating a plot](help:plots-create) |
| Write the data out | [Exporting to Excel](help:export-excel) |
| Repeat the steps on another build | [Macros](help:macros) |
