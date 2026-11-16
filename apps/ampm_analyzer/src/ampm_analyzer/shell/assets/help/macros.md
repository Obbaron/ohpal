---
title: Macros
section: Data
order: 90
keywords: macro, record, stop, run, replay, automate, repeat, recent, issues, steps, batch, file, json, folder, macro folder, documents, shared, network, settings
context: data.macros
---
# Macros

A macro is a recording of the steps you take on the Data tab, saved to a file
so you can run the same routine on another build.

## Recording

1. Press **Record a macro** on the Data toolbar. The button turns into a red
   **Stop**, and the status bar counts the steps as you go.
2. Do the work: add columns, import part data, filter, create plots, export.
3. Press **Stop**. You are asked to name the macro; the save dialog opens in
   your macro folder (see *Where macros are kept* below). Macros are
   `.macro.json` files.

Undoing a step while recording takes it out of the macro. If nothing was
recorded, nothing is saved.

### What is recorded

| Recorded | Not recorded |
| --- | --- |
| Calculated and label columns | Moving between layers |
| Per-part calculations, laser parameters, parts CSV imports | Showing, hiding, reordering, resizing columns |
| Excel imports | Changes to a plot's appearance |
| Renaming, removing, restoring columns | The DataStore setup (mask, correction, columns) |
| Filters | |
| New plots and Excel exports | |

## Running

Press **Run a macro**. Once you have a macro, the button opens a menu: your
**Recent** macros, then the others in your **Macro folder**. **Browse…**
opens any other file, and **Open macro folder** shows the folder.

1. A preview lists the steps. Press **Run** to go ahead.
2. The whole macro is checked against the build first. If any step cannot
   work (a column is missing, the build has no parts, a name is already
   taken, a layer does not exist), a **Macro issues** list explains each
   problem and **nothing is changed**.
3. Otherwise every step runs. The data changes count as **one undo step**.

Plots the macro opened stay open if you undo, and files it exported stay
written.

## Why a macro works on another build

- **Columns are matched by their original names.** If you renamed
  *MeltVIEW melt pool (mean)* to *Meltpool* in one build and *MP* in another,
  the macro still finds it.
- **Part data is read fresh.** Laser-parameter and parts-CSV steps record
  which columns you chose and read them from each build's own CSV.
- **Excel imports ask for the file** every time, so each build can use its own
  workbook.
- **Exports ask where to save** before the macro starts.
- **Plots adapt their layers.** "All layers" and "the layer on screen" follow
  the build; a fixed layer or range must exist in it.

Values you typed, such as a threshold in a filter or the limits in a label
rule, are replayed exactly as recorded.

## Where macros are kept

Macros are saved to, and listed from, the **macro folder**. By default it is
**Documents\AMPM Analyzer\Macros**, created the first time it is needed:
easy to find, backed up with your documents, and kept when the app is
updated.

To change it, open **Settings** (the gear in the title bar) and, under
**Macros**:

- **Open macro folder** shows it in Explorer.
- **Change macro folder…** picks another, for example a shared network
  folder so a team uses the same macros.
- **Use the default folder** goes back to Documents.

You can still save a macro anywhere, and run one from anywhere with
**Browse…**; recently used ones stay on the Run menu wherever they are. If the
chosen folder is not available (a network drive that is offline), the
dialogs open in the default folder instead.

## Editing a macro

The file is plain text. You can open it in a text editor to change a
threshold or delete a step. Keep the structure intact; a file the app cannot
read is reported when you try to run it.

## See also

- [Undo and redo](help:undo-redo)
- [When something goes wrong](help:troubleshooting)
