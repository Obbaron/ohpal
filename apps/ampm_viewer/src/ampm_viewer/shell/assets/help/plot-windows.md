---
title: Plot windows
section: Plots
order: 90
keywords: pop out, dock, window, float, detach, compare, builds, side by side, second monitor
---
# Plot windows

## Pop out

**Pop out** on the plot toolbar moves the plot from its tab into a window of
its own. Put it on another monitor, or line several up side by side.

A popped-out plot is **self-contained**. It keeps its own copy of everything
it needs: the build it came from, the columns and calculations as they were,
its filters and its styling. It therefore keeps working when you open a
different build in the main window. That is one way to compare plots from two
builds: pop one out, open the other build, plot again. For a comparison you
can come back to, save the plot to the [plot library](help:plot-library).

The window has the same toolbar and side panel as a plot tab, including the
[text editor](help:plot-elements). A Layer Viewer keeps its slider and can
still move through its build.

## Dock in

**Dock in** on the window's toolbar brings the plot back as a tab in the main
window. A build must be open in the main window (not for a frozen plot from the
library).

A docked-in plot stays self-contained. It keeps the data and calculations it
had, even if the main window now shows another build, and later column changes
in the main window do not alter it.

A [frozen plot](help:plot-library) can be docked in with no build open.

## Closing

Closing a plot's tab or window discards the plot. A window still open when
you close the app is kept with its build and reopens as a tab.
