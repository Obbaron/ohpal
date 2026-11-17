---
title: Viewing and styling a plot
section: Plots
order: 70
keywords: zoom, pan, rotate, reset view, axes, grid, bbox, legend, colour bar, title, screenshot, image, save, marker, size, opacity, colormap, colour map, scale, log, min, max, range, panel, toolbar, options, equal axes, aspect, 3d view, top, front, side, iso, bins, sort, bandwidth, fill
---
# Viewing and styling a plot

## Moving around

| | 2D plots | 3D plots |
| --- | --- | --- |
| **Drag** | Pan | Rotate |
| **Scroll** | Zoom | Zoom |
| **Right-drag** | Zoom | Zoom |
| **Shift + drag** | Not used | Pan |

**Reset view** on the toolbar frames the data again.

## Toolbar

The toolbar shows only what applies to the plot in front of you, so it
changes as you switch between plots. These are on most plots:

| Button | Does |
| --- | --- |
| **Show/hide panel** | Opens or closes the side panel. |
| **Reset view** | Fits the data in the window. |
| **Axes** | Shows or hides the axes (and axis labels in 3D). |
| **Grid** | Shows or hides the gridlines (the floor grid in 3D). |
| **BBox** | Shows or hides the bounding box. 3D plots only. |
| **Legend** | Shows or hides the colour bar or legend. Only when the plot has one: a plot in a single colour, or a single curve, has none. |
| **Title** | Shows or hides the title. |
| **Screenshot** | Saves the plot as an image (PNG, JPEG, BMP or TIFF). |
| **Pop out** | Moves the plot to its own window; see [Plot windows](help:plot-windows). |

### Plot options

Each kind of plot adds its own options, between the view and export
buttons. Buttons with a small arrow open a menu; in a menu of choices the
current one is ticked.

| Plot | Options |
| --- | --- |
| 2D Scatter, Single Layer | **Equal axes (1:1)**: one unit of X as long as one unit of Y (on by default). Turn it off to stretch the plot to fill the window. |
| Layer Viewer | **Equal axes (1:1)**, and **Previous layer** / **Next layer** to step the slider one layer at a time. |
| 3D Scatter | **3D view**: turn the plot to look from the **Top**, **Front** or **Side**, or at an **Iso** angle. |
| Bar, CoV Summary | **Sort bars**: **By name** or **By value** (tallest first). |
| Histogram | **Bins**: how many bars the range is cut into. |
| Violin | **Quartile box and median**, and **Bandwidth** (Scott or Silverman). |
| KDE | **Fill under curves**, and **Bandwidth**. |
| Contour | **Measured points**, and **Level lines** (when the grid of values is complete). |
| K-Distance Curve | **eps guide line**: the dashed line at the XY radius. |

The options belong to the plot: they carry over when it is popped out into
its own window. A [macro](help:macros) records the plot as it was made, not
later changes to these options.

## Side panel

The panel holds the controls you adjust by eye. Changes apply immediately.
Like the toolbar, it shows only what applies: **Points** on plots drawn as
points (scatter and layer plots), **Colour** when something on the plot
follows a colour map (it names the column the colours come from).

### Points

- **Marker**: disc, square, ring or cross.
- **Size**: the marker size in pixels.
- **Opacity**: lower it to see density where points overlap.

### Colour

Shown when the plot is coloured by a numeric column, or by a map alone.

- **Colour map**: click one of the maps.
- **Scale**: **Linear** or **Log**.
- **Range**: drag the two handles on the colour bar to narrow the range and
  bring out differences. The values under the bar are where the handles sit,
  and the percentages above are their share of the column's full range:
  values below the low handle take the first colour, values above the high one
  the last.

Only **Colour map** is shown where the colours mark groups rather than values: the
curves of a KDE, and a scatter plot coloured by a text column with more
than eight categories. Up to eight categories use a fixed set of distinct
colours, and the Colour group is not shown.

## Text and fonts

The title, axes, category labels and colour bar can be restyled directly on
the plot: click to select, double-click to edit. See
[Editing plot elements](help:plot-elements).

## Saving an image

**Screenshot** saves exactly what the plot shows (title, axes and colour bar
included) at the size it has on screen. Make the window larger for a larger
image. Selection outlines and hover labels are never part of the image.
