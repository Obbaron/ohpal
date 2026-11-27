---
title: Scatter plots
section: Plots
order: 20
keywords: scatter, 2d, 3d, points, colour, markers, rotate, hover, tooltip, sample, bounding box, legend, categories, equal axes, aspect, top, front, side, iso, view, one point per, per part, per specimen, mean, cov, statistic, trend line, regression, fit, linear, r squared, r2, p-value, correlation, shape by, marker shape, symbols, orientation, rotation, label points, point labels, names, specimen
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

## One point per part

**One point per** in the dialog draws a point for each value of a column
instead of each row: each part, say, or each specimen named in an
[alias column](help:columns-excel). Beside **X** and **Y**, choose what the
point shows of that group's rows:

| Statistic | The group's... |
| --- | --- |
| **Mean** | average |
| **Median** | middle value |
| **SD** | sample standard deviation |
| **CoV (%)** | coefficient of variation: SD / mean x 100 |
| **Min**, **Max** | smallest, largest value |

So a measurement made on each part (a distortion, a density, brought in
**from Excel**) against the mean melt pool of that part's rows is: one point
per `part_id`, X = the melt pool column at **Mean**, Y = the measurement. A
column with one value per part is that value whatever the statistic, and its
axis is named plainly; otherwise the axis says what it shows (*Mean of
Meltpool*, *CoV of Meltpool (%)*). Rows in no part, and DBSCAN's noise, are
left out. The colour column is the group's mean (a number) or its value
(text). Hover a point for its group, its X and Y and how many rows they are
over.

Choosing a group switches the layers to **All layers**: a part is usually
wanted whole. Like every plot, the statistics are worked out from up to
1,000,000 rows spread evenly through the build; for numbers from every row,
use a summary [export](help:export-excel).

## Trend line

**Trend line** (in the dialog, or on the toolbar) draws the least-squares
straight line through the points on screen, across their X range, and labels
it in a corner of the plot:

- the equation, *y = 7.72x - 997*;
- R², how much of Y's spread the line accounts for (0 to 1);
- p, the chance of a slope at least this steep if X and Y were unrelated
  (*p < 0.001* when it is tiny).

On a plot of every row the line goes through every row; with one point per
part, through the parts' points. Fewer than three points, or points all at
one X, have no line. On a log axis the line is still the straight-line fit of
the values themselves, drawn curved.

Double-click the label to [edit](help:plot-elements) it: font, size, colour,
which corner, what it shows (the equation, R², p, the number of points), and
the line's colour, width and dashes. The trend line is also on
[Mean ± SD](help:plot-mean-sd) plots, through the group means.

## Shapes and labels

Two more choices in the dialog, for a 2D Scatter (of every row or one point
per group) and a [Mean ± SD](help:plot-mean-sd) plot:

- **Shape by** draws each value of a column in its own marker shape: disc,
  square, triangle, diamond and so on, in the column's natural order (a
  ninth value starts the shapes again). The legend gets a section for the
  shapes, under the colours' when the points are coloured by a text column;
  beside a colour bar it sits inside the plot, top right. So a colour can show
  one setting and a shape another: colour by scan length, shape by build
  orientation. The side panel's **Marker** is off while the shapes come from
  a column.
- **Label points** writes a column's value beside each point (a specimen's
  name, say). Labels are drawn for up to 300 points; a plot of more has none.
  On a grouped plot the value is the group's (its first, when the group's
  rows differ).

The labels are a [plot element](help:plot-elements): double-click one to set
their font, size, colour and side (right, left, above, below, or above right,
the start on Mean ± SD plots so they clear the error bars). They keep their
distance from the points as you zoom. Hover a point for its shape and label
columns too.

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
