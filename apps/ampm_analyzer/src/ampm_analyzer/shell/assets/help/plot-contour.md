---
title: Contour plots
section: Plots
order: 60
keywords: contour, contourf, filled, bands, levels, grid, parameter, map, heatmap, hatch speed, power, measured points, process window, interpolation, smooth, colour bar
context: plot.Contour
---
# Contour plots

A contour plot shows how a **value** changes over two **parameters**, as
smooth filled bands of colour. Its usual job is a parameter study: mean melt
pool (the value) against hatch speed and hatch power (the parameters).

- **X** and **Y**: the two parameters. Both must be numeric.
- **Value (colour)**: what the colours show.
- **Show measured points**: marks each combination that actually has data.

It always covers the whole build.

## Reading the plot

- **Bands.** The value range is cut into round levels, and everything between
  two levels gets one colour. Thin lines mark the level boundaries.
- **Colour bar.** It shows the same bands, labelled at the levels.
- **Between the measured points the surface is interpolated.** The plot draws
  a smooth surface through the values you measured; it has no data in
  between. Turn on **Show measured points** to see where the real data is,
  and treat features that sit between points with caution.
- **Blank areas** are regions with no measured combinations around them. The
  surface is only drawn between points, never beyond them.
- The surface never shows a value above the highest or below the lowest one
  measured.

## Preparing the data

The plot wants **one value for each combination of X and Y**. If several rows
share a combination, their mean is used.

So make the value a per-part number first:

1. [Parts ▸ Add laser parameters](help:parts) brings in *Hatch Speed*,
   *Hatches Power* and the other settings, the same for every row of a part.
2. [Parts ▸ Per-part calculation](help:parts) gives each part its mean (or
   CoV) of the signal.
3. Plot X = *Hatch Speed*, Y = *Hatches Power*, Value = the per-part column.

A complete grid of combinations (every speed at every power) gives the
smoothest result. With gaps, the plot interpolates between whichever points
exist, leaves the rest blank and does not draw the level lines.

## Colours

A contour plot starts on the **viridis** colour map. Change the map in the
side panel, and narrow **Min** and **Max** to spend the bands on the part of
the range you care about: the levels are recalculated to fit.

## See also

- [Viewing and styling a plot](help:plot-view): colour map and range.
- [Editing plot text](help:plot-elements): the title, axes and colour bar
  text.
