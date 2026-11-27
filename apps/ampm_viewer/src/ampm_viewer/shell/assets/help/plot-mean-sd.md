---
title: Mean ± SD plots
section: Plots
order: 55
keywords: mean, sd, standard deviation, error bars, standard error, se, confidence interval, ci, archimedes, density, repeats, replicates, energy density, samples template, measurement, trend line, regression, fit, r squared, p-value, x error bars, horizontal error bars, shape by, label points
context: plot.Mean ± SD
---
# Mean ± SD plots

A **Mean ± SD** plot draws one point per part (or per group) at the mean of
its measurements, with an error bar. It is the plot for measurements made on
the parts after the build, such as an Archimedes density measured three
times per part, against a process setting such as the energy density.

## Making one

1. Fill in the [samples template](help:create-excel): add a column for each
   repeat of a measurement, for example **Density (1)**, **Density (2)** and
   **Density (3)**, one row per part.
2. Bring each column into the table with
   [Add column ▸ Excel](help:columns-excel); each import starts on the next
   column you filled in. Import the template's **Hatches Power** and
   **Hatch Speed** too, or use the parts CSV's laser parameters.
3. For energy density, add a [calculation](help:columns-calculation) such as
   `[Hatches Power] * 1000 / [Hatch Speed]` (W and mm/s give J/m).
4. **New plot ▸ Mean ± SD**:
   - **X**: the setting to plot against (it starts on a column whose name
     has "energy" in it).
   - **Values**: tick the measurement and its repeats. Ticking one of a
     numbered set (**Density (1)**) ticks the rest.
   - **One point per**: `part_id` for one point per part. Choose another
     column, such as the energy density, to pool every part that shares it.
   - **Error bars**: **SD**, **SE**, **95% CI** or **None**. Tick **On X
     too** for error bars across as well (see below).
   - **Colour by**, **Shape by** and **Label points** are optional: see
     [Shapes and labels](help:plot-scatter).

## What each point is

The table has a row for every measured point of the build, so an imported
density is on thousands of rows per part. Each part counts **once**: its
value in each value column is the mean of its rows (for an imported value,
just that value). A point's values are then every part's value in every
value column, so three repeats of one part give n = 3, and two parts
pooled give n = 6.

- **Mean**: the average of those values.
- **SD**: the sample standard deviation (n - 1), as Excel's `STDEV.S`.
- **SE**: SD divided by the square root of n.
- **95% CI**: the 95% confidence interval of the mean, t × SE with
  Student's t for n - 1.
- A point with a single value has no error bar.

Points in no part, and DBSCAN's noise, are left out. Hover over a point to
see its group, X, mean ± error, SD and n. Change the error bars from the
toolbar's **Error bars** menu.

## Error bars on X

When X differs between the parts of a group (the mean melt pool of each
specimen, pooled by scan length, say), **On X too** in the dialog, or
**Error bars on X** on the toolbar, adds a bar across each point: X's mean ±
its error over the group's parts, each part counted once, of the same kind
as the vertical bar (SD, SE or 95% CI). A group whose parts share one X (a
process setting) has none. The hover shows X ± its error.

## Trend line

**Trend line** (in the dialog or on the toolbar) draws the least-squares line
through the means, labelled with its equation, R² and p: see
[Scatter plots](help:plot-scatter). For one point per part with a
statistic other than the mean (a CoV, say) on an axis, use a 2D Scatter with
**One point per**.

## Axes

Click an axis and open it in the side panel to set its **Minimum** and
**Maximum** (empty is automatic) or to put it on a **Log scale**; see
[Editing plot elements](help:plot-elements). The marker size and shape are
in the **Points** editor.
