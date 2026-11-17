---
title: Renaming, removing and restoring columns
section: Data
order: 50
keywords: rename, remove, delete, restore, hide, required, column, header
---
# Renaming, removing and restoring columns

## Rename

Double-click a column's header and type the new name, or select the column and
press **Rename column** on the toolbar. You can also edit the **Name** field
in the side panel.

A rename is carried everywhere the column is used: formulas, label rules,
filters and open plots all switch to the new name. Two columns cannot share a
name.

## Remove

Select one or more columns and press **Remove column**.

- Removing a **calculated, label or imported** column deletes it.
- Removing a column that **came from the build** takes it out of the table,
  plots and exports until you restore it.
- **Required columns** cannot be removed: position, *Start time*, *layer*,
  *Z* and *LaserVIEW (mean)*.

Formulas that use a removed build column keep working. But if you delete a
calculated column that another calculation depends on, the dependent column
disappears as well, because it can no longer be computed. Undo brings both
back.

## Restore

**Add column ▸ Restore column** lists the build columns you have removed.
Choose one to bring it back. The entry only appears when there is something to
restore.

## Hiding is not removing

**Show/hide columns** only changes what the table displays. A hidden column
still exists for formulas, filters, plots and exports. Remove a column only
when you want it gone.

All of these can be [undone](help:undo-redo).
