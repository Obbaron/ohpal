---
title: Filters
section: Data
order: 60
keywords: filter, condition, rows, chip, remove filter, reset filters, threshold, box, region, range
---
# Filters

A filter keeps only the rows that meet a condition. Filters apply to the
table, to plots created while they are active, and (if you choose) to
exports.

## Adding a filter

Press **Filter** on the Data toolbar and write a condition:

```
[Meltpool] >= 500
[X] >= -32 and [X] <= -28 and [layer] == 1
[region] == "R1"
```

- Columns go in square brackets; typing `[` lists them.
- Compare with `== != < <= > >=`, and combine with `and`, `or`, `not`.
- Text values go in double quotes.
- The templates on the dialog (*Spatial box + layer*, *Value threshold*,
  *Category match*, *Z range*, *Single layer*) fill in a starting point when
  clicked.

The line under the box confirms a valid condition or says what is wrong.

## Several filters

Add as many as you need; a row must pass **all** of them. Each active filter
shows as a chip above the table, next to a count of rows shown out of the
total.

- Click a chip's text to **edit** that filter.
- Click its **✕** to remove it.
- **Remove filter** on the toolbar removes the most recent one.
- **Reset filters** removes them all.

## Filters and plots

A plot uses the filters that were active **when it was created** and keeps
them. Changing filters afterwards changes the table, not the plots already
open, which lets you compare a filtered plot with an unfiltered one. To plot
with different filters, change them and create a new plot.

## Filters and calculations

Filters are applied after columns are calculated. A summary such as
`mean([Meltpool])` is therefore taken over all the rows, not only the filtered
ones. To restrict a calculation, use `where` inside the formula; see
[Calculated columns](help:columns-calculation).

Filters can be [undone](help:undo-redo) and are recorded in
[macros](help:macros).
