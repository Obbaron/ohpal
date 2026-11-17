---
title: Editing plot elements
section: Plots
order: 80
keywords: font, text, title, axis, label, tick, ticks, number format, decimals, scientific, gridlines, axis line, size, bold, italic, colour, element, edit, select, default, reset, style, rename plot, colour bar, position, below, thickness, gap, legend, frame, corner, category, data, points, markers, bars, bar width, outline, curves, line width, violins, contour, alignment
context: plot.elements
---
# Editing plot elements

Most of what is drawn on a plot can be changed in place: the title, the
axes, the colour bar, the legend and the data itself.

## Select and edit

- **Click** an element to select it. An outline marks the selection.
- **Double-click** it to open its editor in the side panel.
- Edits apply as you make them.
- Click the **‹** arrow, or an empty part of the plot, to go back to the
  plot's usual controls.

Once the editor is open, clicking another element switches the editor to it.
The pointer turns into a hand over anything that can be edited. The data
counts where its tooltip shows: on a point, a bar, a curve or a violin (and
anywhere on a filled contour).

## What can be edited

| Element | Properties |
| --- | --- |
| **Title** | Text, font, size, bold / italic, colour, and alignment (left, centre or right). The title's text is the plot's name, so it also renames the tab. |
| **X axis, Y axis** | The axis title (text, font, size, style, colour); the tick labels (font, size, colour); the number of ticks and their format; the axis line; the gridlines. |
| **3D axis labels** | Text, font, size, style, colour for each of X, Y and Z. |
| **Category labels** | Font, size, style, colour and angle of the names under a bar, CoV or violin chart. |
| **Colour bar** | The label; the numbers (font, size, colour, how many, format); where it sits (right of the plot or below it), its gap to the plot and its thickness. |
| **Legend** | The title; the names (font, size, colour); where it sits (beside the plot or inside a corner of it); the frame and its colour. |
| **The data** | Depends on the plot, see below. |

Leave an axis, colour-bar or legend **Text** empty to use the column's name;
it then follows the column if you rename it.

## Ticks and numbers

- **Number of ticks**: **Auto** lets the plot choose; a number asks for about
  that many, at round values.
- **Format**: **Automatic**, **Fixed decimals** (with **Decimals** setting
  how many) or **Scientific** (1.23e+03).
- The colour bar takes the same settings for its numbers. On a filled
  contour the bar is labelled at its levels; only the format applies.

## Crowded labels

Labels never overlap. Category names that don't fit side by side are turned
(**Angle: Automatic** turns them only as far as needed: 45 degrees, then
vertical), and if they are still too close only every 2nd, 3rd... is shown;
zooming in brings the rest back. Choose **Horizontal**, **45°** or
**Vertical** to fix the angle. The strip under the chart deepens to fit
turned names.

Axis numbers and colour-bar numbers that would overlap (a big font, many
ticks, a long format) are thinned the same way; the ticks stay.

## Axis line and gridlines

**Show the axis line** draws a line along the axis in the colour you choose.
The gridlines have a colour and an opacity; there is one set for the plot,
so either axis's editor changes them.

## The colour bar's place

Choose **Right of the plot** or **Below the plot**. **Gap to the plot** adds
space between them, and **Bar thickness** sets the bar's width in pixels
(**Auto** follows the plot's size).

## The legend

A plot coloured by a text column, and a KDE plot of groups, get a legend: a
box with a swatch and a name for each group. Put it **Outside, right** (the
plot narrows to make room) or **Inside** one of the four corners (it covers
the data there, on a light backing). When there are more groups than fit,
the last row counts the rest.

## The data

| Plot | Properties |
| --- | --- |
| **Scatter, layer views, 3D** | Marker, size, opacity, colour map, scale. These are the same settings as the side panel's **Points** and **Colour** boxes, and the two stay in step. |
| **Bar, histogram, CoV** | Bar width (as a share of each bar's slot), an outline and its colour, the colour map. |
| **KDE** | Line width, fill opacity (**Auto** fades as curves are added), the colour map. |
| **K-distance curve** | The curve's colour and width, the eps guide's colour. |
| **Violin** | Fill opacity, outline colour, the colour map. |
| **Contour** | The level lines (colour, opacity, width), the measured points' size, the colour map. |

## Hidden elements make room

Turning off the title, the axes or the legend from the plot's toolbar gives
their space to the plot, so it fills as much of the window as it can.

## Fonts

Four families are built in, so plots look the same on every computer:
**Open Sans**, **Liberation Sans** (metric-compatible with Arial),
**Liberation Serif** (Times New Roman) and **Liberation Mono** (Courier New).

## Defaults and reset

- **Set as default** makes the element's styling the starting point for new
  plots. Its text is never part of the default, and plots already open keep
  their own styling. For the data, the default covers new plots of the same
  kind of drawing (points, bars, curves...).
- **Reset ▸ To my default** returns the element to your saved default.
- **Reset ▸ To the built-in look** returns it to the original styling. Press
  **Set as default** afterwards to clear a saved default.

Reset keeps the text you typed.

## Good to know

- The plot makes room as text grows: the title and axis strips get deeper and
  the Y axis widens to fit its numbers.
- Styling travels with a plot when it is
  [popped out or docked](help:plot-windows).
- Element edits are not undo steps and are not recorded in
  [macros](help:macros).
