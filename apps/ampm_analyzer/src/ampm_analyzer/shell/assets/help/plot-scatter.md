---
title: Scatter plots
section: Plots
order: 20
keywords: scatter, 2d, 3d, points, colour, markers, rotate, hover, tooltip, sample, bounding box, legend, categories, equal axes, aspect, top, front, side, iso, view
context: plot.2D Scatter, plot.3D Scatter
---
# Scatter plots

## 2D Scatter

Points on an X and a Y axis, optionally coloured by a third column. With the
position columns on the axes it is a top-down view of the plate, drawn to
scale: one unit of X is as long as one unit of Y, so parts are not stretched.

It starts on a single layer, because a top-down view of many layers draws them
on top of each other. Choose **All layers** or a **Range** in the dialog when
that is what you want, for example to plot one signal against another.

When the axes are not positions (one signal against another, say), turn off
**Equal axes (1:1)** on the toolbar so the plot fills the window.

## 3D Scatter

Points in space, with a floor grid and a bounding box. Use the position
columns and **Z** to see the build as printed, or put any three columns on the
axes. It starts on all layers.

**3D view** on the toolbar turns the plot to a set angle: **Top** (looking
down on the plate), **Front**, **Side** or **Iso**. The axes keep their true
scale, so a build only a few layers tall looks thin from the front.

## Colours and the legend

Coloured by a numeric column, the points follow a colour map, with a colour
bar beside the plot. Coloured by a text column (`part_id`, a
[label](help:columns-label)), each category gets its own colour and a legend
names them, in natural order (Part(2) before Part(10)). A category keeps its
colour whatever layers are shown. Without a colour column there is no
legend, and no **Legend** button.

## Reading values

Hover a point to see its values: the plotted columns, the colour column, and
its part and layer when the data has them.

## Large builds

A scatter plot draws at most about 150,000 points. When the chosen layers hold
more, an even random sample is drawn: the picture is representative, but not
every point is there. Narrow the layers or add a [filter](help:filters) to see
everything in a region.

In 2D the markers grow slightly when you zoom out so that thin features stay
visible, and return to their set size as you zoom in.

## See also

- [Viewing and styling a plot](help:plot-view): moving around, colours, marker
  size.
- [Layer plots](help:plot-layers): to step through the build layer by layer.
