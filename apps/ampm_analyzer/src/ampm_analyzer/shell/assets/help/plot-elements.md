---
title: Editing plot text
section: Plots
order: 80
keywords: font, text, title, axis, label, tick, size, bold, italic, colour, element, edit, select, default, reset, style, rename plot, colour bar, category
context: plot.elements
---
# Editing plot text

The text on a plot can be changed in place: what it says, its font, size,
style and colour.

## Select and edit

- **Click** an element to select it. An outline marks the selection.
- **Double-click** it to open its editor in the side panel.
- Edits apply as you make them.
- Click the **‹** arrow, or anywhere on the data, to go back to the plot's
  usual controls.

Once the editor is open, clicking another element switches the editor to it.
The pointer turns into a hand over anything that can be edited.

## What can be edited

| Element | Properties |
| --- | --- |
| **Title** | Text, font, size, bold / italic, colour. The title's text is the plot's name, so it also renames the tab. |
| **X axis, Y axis** | The axis title (text, font, size, style, colour) and, separately, the tick labels (font, size, colour). |
| **3D axis labels** | Text, font, size, style, colour for each of X, Y and Z. |
| **Category labels** | Font, size, style, colour of the names under a bar chart. |
| **Colour bar** | The label (text, font, size, style, colour) and the numbers at its ends (font, size, colour). |

Leave an axis or colour-bar **Text** empty to use the column's name; it then
follows the column if you rename it.

## Fonts

Four families are built in, so plots look the same on every computer:
**Open Sans**, **Liberation Sans** (metric-compatible with Arial),
**Liberation Serif** (Times New Roman) and **Liberation Mono** (Courier New).

## Defaults and reset

- **Set as default** makes the element's styling the starting point for new
  plots. Its text is never part of the default, and plots already open keep
  their own styling.
- **Reset ▸ To my default** returns the element to your saved default.
- **Reset ▸ To the built-in look** returns it to the original styling. Press
  **Set as default** afterwards to clear a saved default.

Reset keeps the text you typed.

## Good to know

- The plot makes room as text grows: the title and axis strips get deeper and
  the Y axis widens to fit its numbers.
- Styling travels with a plot when it is
  [popped out or docked](help:plot-windows).
- Text edits are not undo steps and are not recorded in [macros](help:macros).
