---
title: When something goes wrong
section: Reference
order: 30
keywords: error, problem, missing, greyed, disabled, fail, slow, empty, blank, issues, troubleshooting, no data, not found, memory
---
# When something goes wrong

## A button or option is greyed out

Hover it: the tooltip says what is missing. The usual causes:

| Greyed out | Needs |
| --- | --- |
| **Apply mask** | An STL in the build folder. |
| **Assign parts** | A parts CSV or a DHXML. *Direct* and *DBSCAN* need the CSV; *DHXML* needs the DHXML. |
| **Apply correction** | Both *MeltVIEW melt pool (mean)* and *LaserVIEW (mean)*. |
| **Add laser parameters**, **Import parts CSV** | A parts CSV. |

The **Parts** menu is absent altogether when the build has no part
assignment. Rebuild the DataStore with **Assign parts** ticked.

## The table is empty, or a layer cannot be reached

The layer selector skips layers without data. A layer has no data when it was
outside the range you built, or when the mask found no part on it. To include
more layers, rebuild the DataStore with a wider range.

## A column I expected is missing

- It may be **hidden**: check **Show/hide columns**.
- It may have been **removed**: check **Add column ▸ Restore column**.
- It may not have been **loaded**: the DataStore setup page decides which
  columns are imported. Rebuilding with it ticked brings it in.
- A calculated column disappears if a column it depends on was deleted.

## Imported part values are blank

The values are matched on `part_id`. Blank cells mean the part names in the
file do not match the names in the table. The message after an import says
how many parts were matched.

## "Macro issues"

The macro was checked against this build and at least one step cannot work
here; nothing was changed. Each line names the step and the reason: a column
this build does not have, a name already in use, a layer that does not exist,
or no part assignment. Fix the cause (or edit the macro) and run it again. See
[Macros](help:macros).

## DBSCAN part assignment failed

No cluster could be matched to a part, or the computer ran out of memory.
The build stays open without a part column. Rebuild with **Direct** part
assignment, which suits most builds, or reduce the layer range.

## A plot says a column is not in the data

The plot uses a column that has since been removed. Restore the column, or
undo the removal, and the plot redraws.

## A plot shows a message instead of drawing

- *No rows to plot*: the plot's layers and filters leave nothing. Check the
  filters that were active when you created it.
- A message about **VisPy** or the canvas: the graphics library could not
  start. Update the graphics driver; if you run from source, check that VisPy
  is installed.

## It is slow

- The first build of a DataStore converts every layer and takes time; later
  opens are fast.
- Plots of **All layers** read the whole build. A range, or a filter, is
  quicker.
- DBSCAN is slow by nature; see
  [Setting up the DataStore](help:datastore-setup).

## Still stuck

Open the [log](help:settings-log), export it, and send it along with a
description of what you were doing.
