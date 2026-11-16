---
title: KDE and violin plots
section: Plots
order: 55
keywords: kde, density, kernel density, violin, distribution, spread, quartile, median, bandwidth, scott, silverman, compare parts, curves, legend
context: plot.KDE, plot.Violin
---
# KDE and violin plots

Both show the whole **distribution** of a value, not just its average: where
readings cluster, how widely they spread, whether there is a second group of
readings. Use them to compare parts that have similar means but behave
differently.

## KDE

A kernel-density estimate (KDE) is a smoothed histogram: a curve whose height
shows how common each value is. The area under each curve is 1.

- **Column**: the value to look at.
- **One curve per**: a grouping column, usually `part_id`, to draw one curve
  per part. Choose *none* for a single curve over all the rows.
- **Bandwidth**: how smooth the curves are. **Scott** suits most data;
  **Silverman** is a little smoother. Both are the rules `gaussian_kde` uses.

Each curve has its own colour, and a legend beside the plot names them (with
very many groups, every second or third name is shown; hover a curve to
identify it). The side panel's **Map** changes the colours. Hover a curve to
read the group, the value, the density there and how many rows the curve is
built from.

Every row is used: nothing is sampled, however large the build.

## Violin

One **violin** per category, side by side. Each is the KDE of that
category's values, mirrored so it reads as a shape: wide where values are
common, thin where they are rare.

- **Category**: what each violin is, usually `part_id`, a
  [label](help:columns-label) or `layer`. At most 60 categories.
- **Value**: the column to show.
- **Bandwidth**: as for the KDE.
- **Show quartile box and median**: the dark bar inside each violin runs from
  the first to the third quartile (the middle half of the values), the thin
  line from the minimum to the maximum, and the white mark is the median.

Each violin spans exactly the range of its own values, and all have the same
greatest width. Violins are coloured by their median, like bars by their
height, with a colour bar; the side panel's colour controls apply. Hover a
violin for its count, quartiles, median, minimum and maximum.

## Reading them

- **Two humps** mean two populations of readings in the same part, for
  example the hatch and the contour of a part, or a change partway up a
  build.
- **A long thin tail** means a few extreme readings; the median and the box
  are not affected by them, the mean would be.
- To put a number on spread, use a [CoV summary](help:plot-cov).

## See also

- [Bar charts and histograms](help:plot-bars)
- [Viewing and styling a plot](help:plot-view)
