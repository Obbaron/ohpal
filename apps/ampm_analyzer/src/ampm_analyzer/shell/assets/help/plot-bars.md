---
title: Bar charts and histograms
section: Plots
order: 40
keywords: bar, histogram, bins, category, aggregate, mean, count, as-is, distribution
context: plot.Bar, plot.Histogram
---
# Bar charts and histograms

## Bar

One bar per **category**, as tall as a **value** reduced over that category's
rows.

- **Category**: the column that defines the bars, such as `part_id`, `layer`
  or a [label](help:columns-label).
- **Value**: the column to measure.
- **Aggregate**: how to reduce the value within each category (mean, median,
  sum, min, max, count or first).

Choose **as-is** when the value is already one number per category, for
example a CoV you calculated `by [part_id]`. It takes that number directly
instead of averaging it again.

The bars are coloured by their height, with a colour bar. Hover a bar to read
its value.

## Histogram

The distribution of one **column**: its range is cut into **bins** and each
bar counts the rows that fall in a bin. More bins show more detail; fewer
give a smoother shape. Hover a bar for its range and count.

## Layers

Both start on **All layers**. Choose **Single** or **Range** in the dialog to
look at part of the build.

## See also

- [CoV summary](help:plot-cov): a ready-made bar chart of signal stability.
- [Editing plot text](help:plot-elements): to restyle the category labels and
  axes.
