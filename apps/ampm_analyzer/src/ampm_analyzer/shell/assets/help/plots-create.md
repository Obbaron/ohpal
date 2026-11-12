---
title: Creating a plot
section: Plots
order: 10
keywords: plot, new plot, chart, graph, create, layers, span, range, colour by, type, tab
context: plot
---
# Creating a plot

Plots are made from the Data tab: press **New plot** and choose a type. A
short dialog asks which columns to use, and the plot opens in its own tab.

## Plot types

| Type | Shows | Read more |
| --- | --- | --- |
| **2D Scatter** | Points on two axes, coloured by a third column | [Scatter plots](help:plot-scatter) |
| **3D Scatter** | Points in space: the build as it was printed | [Scatter plots](help:plot-scatter) |
| **Layer Viewer** | One layer at a time, with a slider to move through the build | [Layer plots](help:plot-layers) |
| **Single Layer** | One chosen layer, fixed | [Layer plots](help:plot-layers) |
| **Bar** | One bar per category | [Bar charts and histograms](help:plot-bars) |
| **Histogram** | The distribution of one column | [Bar charts and histograms](help:plot-bars) |
| **CoV Summary** | The stability of a signal for each part or group | [CoV summary](help:plot-cov) |
| **Contour** | A value over a grid of two parameters | [Contour plots](help:plot-contour) |

## Choosing columns

Any column can go on any axis, including ones you calculated or imported.
**Colour by** paints the points by a column: a number gives a colour scale
with a colour bar; text gives one colour per value. Choose the *none* entry
for a single colour.

## Choosing layers

Scatter, bar and histogram plots ask which layers to draw:

- **All layers**: the whole build.
- **Single**: one layer.
- **Range**: from one layer to another.

A plot's layers are its own. Moving the Data tab to another layer does not
change a plot, and two plots can show different layers side by side.

## What a plot follows afterwards

- **Column changes**: a plot redraws when you rename a column or change a
  calculation it uses.
- **Filters**: a plot keeps the [filters](help:filters) that were active when
  it was created.
- **Its title** is the tab's name. Rename it by editing the title; see
  [Editing plot text](help:plot-elements).

## Next

- [Viewing and styling a plot](help:plot-view)
- [Plot windows](help:plot-windows)
