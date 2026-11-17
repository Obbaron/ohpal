---
title: Undo and redo
section: Data
order: 80
keywords: undo, redo, ctrl+z, history, revert, mistake
---
# Undo and redo

The **Undo** and **Redo** buttons at the top right step back and forward
through your changes to the data. The keys are **Ctrl+Z** to undo and
**Ctrl+Shift+Z** (or **Ctrl+Y**) to redo. Hover a button to see what it will
undo or redo.

## What can be undone

- Adding, overwriting, removing and restoring columns: calculations, labels,
  per-part calculations, laser parameters, parts CSV and Excel imports.
- Renaming a column, including the rename it caused in formulas and plots.
- Showing and hiding columns.
- Adding, editing and removing filters.
- Running a [macro](help:macros): the whole run is a single step.

## What cannot

- Moving between layers, and reordering or resizing columns.
- Creating a plot or changing how it looks.
- Exporting a file.
- Building or rebuilding the DataStore.

While you are typing in a text box, Ctrl+Z undoes your typing as usual.

## How long it lasts

The history holds the last 50 steps for the build you have open. It starts
empty each time a build is opened or rebuilt.
