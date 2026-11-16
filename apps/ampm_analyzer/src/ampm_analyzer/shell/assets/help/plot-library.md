---
title: The plot library
section: Plots
order: 95
keywords: library, plot library, save plot, frozen, freeze, snapshot, compare, builds, side by side, share, export plot, keep, folder, ampmplot
context: file.library
---
# The plot library

The plot library keeps **frozen** plots: a plot together with the data it
draws. A frozen plot always shows the numbers of the build it was saved from,
so you can open plots of different builds side by side and compare them, now
or later, with or without a build open.

## Save a plot to the library

Press **Save to plot library** on the plot's toolbar and give it a name. The
library keeps:

- the plot's data: the rows it draws and only the columns it uses (its axes,
  colour, grouping, and the part and layer shown on hover);
- everything about its look: the title, styling, colour map and range, and
  its toolbar options;
- where it came from: the build's name and when it was saved.

A **Layer Viewer** keeps every layer it can show, so its slider still works.
If a plot would make a large file, the app says how large and asks first.

## Open a plot from the library

- **File ▸ Plot library** lists the saved plots, newest first, with the
  build each came from. Double-click one, or select it and press **Open**.
- On the Data tab, **New plot ▸ Open from the plot library…** goes there too.
- **Browse…** opens a saved plot from any other folder.

The plot opens in a tab named after its title and its build, for example
*Melt pool map · JR299*. Its styling can still be changed, and it can be
[popped out](help:plot-windows) next to another plot.

A frozen plot does not change with the open build: column changes, filters
and rebuilds leave it as it was saved. Opening another build leaves it open.

## The library folder

Plots are saved to **Documents\AMPM Analyzer\Plots** unless you choose
another folder in **Settings ▸ Plot library** (a shared team folder, for
example). **Open folder** on the library page shows it.

Each plot is one `.ampmplot` file, so it can also be copied or emailed.

## Good to know

- A build's own plots reopen with it without the library; see
  [Creating a plot](help:plots-create). The library is for keeping a plot as
  it is.
- Saving the same name again replaces the file.
