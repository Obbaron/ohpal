---
title: Contour plots
section: Plots
order: 60
keywords: contour, grid, parameter, map, heatmap, hatch speed, power, measured points, process window
context: plot.Contour
---
# Contour plots

A contour plot lays a **value** out over a grid of two **parameters**. Its
usual job is a parameter study: mean melt pool (the value) against hatch speed
and hatch power (the parameters), one cell per combination that was printed.

- **X** and **Y**: the two parameters. Both must be numeric.
- **Value (colour)**: what each cell shows.
- **Show measured points**: marks each combination that actually has data.

It always covers the whole build.

## Preparing the data

The plot expects **one value for each combination of X and Y**. Each distinct
X is a column of the grid and each distinct Y a row; combinations with no data
are left blank.

So make the value a per-part number first:

1. [Parts ▸ Add laser parameters](help:parts) brings in *Hatch Speed*,
   *Hatches Power* and the other settings, the same for every row of a part.
2. [Parts ▸ Per-part calculation](help:parts) gives each part its mean (or
   CoV) of the signal.
3. Plot X = *Hatch Speed*, Y = *Hatches Power*, Value = the per-part column.

If you plot a raw signal instead, each cell shows just one of the many
readings for that combination, which is rarely what you want.

## See also

- [Viewing and styling a plot](help:plot-view): colour map and range.
