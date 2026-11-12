---
title: Viewing and styling a plot
section: Plots
order: 70
keywords: zoom, pan, rotate, reset view, axes, grid, bbox, legend, colour bar, title, screenshot, image, save, marker, size, opacity, colormap, colour map, scale, log, min, max, panel
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

| Button | Does |
| --- | --- |
| **Show/hide panel** | Opens or closes the side panel. |
| **Reset view** | Fits the data in the window. |
| **Axes** | Shows or hides the axes (and axis labels in 3D). |
| **Grid** | Shows or hides the gridlines (the floor grid in 3D). |
| **BBox** | Shows or hides the bounding box (3D only). |
| **Legend** | Shows or hides the colour bar. |
| **Title** | Shows or hides the title. |
| **Screenshot** | Saves the plot as an image (PNG, JPEG, BMP or TIFF). |
| **Pop out** | Moves the plot to its own window; see [Plot windows](help:plot-windows). |

The **Select**, **Clear** and **Invert** controls are reserved for selecting
points on the plot and are not active yet.

## Side panel

The panel holds the controls you adjust by eye. Changes apply immediately.

### Points

- **Marker**: disc, square, ring or cross.
- **Size**: the marker size in pixels.
- **Opacity**: lower it to see density where points overlap.

### Colour

Available when the plot is coloured by a numeric column.

- **Map**: the colour map.
- **Scale**: **Linear** or **Log**.
- **Min** and **Max**: narrow the colour range to bring out differences.
  They are percentages of the column's full range: values below Min take the
  first colour, values above Max the last.

## Text and fonts

The title, axes, category labels and colour bar can be restyled directly on
the plot: click to select, double-click to edit. See
[Editing plot text](help:plot-elements).

## Saving an image

**Screenshot** saves exactly what the plot shows (title, axes and colour bar
included) at the size it has on screen. Make the window larger for a larger
image. Selection outlines and hover labels are never part of the image.
