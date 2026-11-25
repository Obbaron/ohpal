---
title: Parts
section: Data
order: 55
keywords: parts, part_id, per-part, laser parameters, parts csv, quantam, import, hatch, power, speed, instance, cov, assignment
---
# Parts

When a build has a part assignment, every row carries a `part_id`, and a
**Parts** menu appears on the Data toolbar. If the menu is missing, the build
was made without **Assign parts**; see
[Setting up the DataStore](help:datastore-setup).

## Per-part calculation

A shortcut for the most common calculation: one value per part.

Choose a **Signal**, how to **Reduce** it (mean, median, standard deviation,
variance, CoV, min, max or sum) and a name. Every row of a part gets that
part's value.

Choosing **CoV** adds three columns: the per-part mean, the per-part standard
deviation, and their ratio.

It writes an ordinary [calculated column](help:columns-calculation)
(`mean([Meltpool]) by [part_id]`), so you can do the same by hand with any
formula.

## Import from parts CSV

Opens the parts CSV section by section (Strategy, Scan Volume, …; the
Parent Parts section is the CSV's own index of parts and isn't offered). Tick
the columns you want from any section; the count at the bottom shows how many
are staged. **Import** adds them all in one step, and the message afterwards
says how many of the build's parts were matched. Drag the window's edges or
its corner to make it bigger.

The laser parameters each part was built with are in the **Scan Volume**
section: *Hatches Power*, *Hatches Point Distance*, *Hatches Exposure Time*
and the border and contour settings. Hatch speed is the point distance over
the exposure time: a [calculated column](help:columns-calculation) such as
`[Hatches Point Distance] / [Hatches Exposure Time] * 1000` gives it in mm/s.
These columns make parameter studies possible: plot the mean melt pool per
part against hatch speed and power in a [contour plot](help:plot-contour).

This needs the parts CSV; without one it is greyed out.

### Matched by position

The parts CSV and the build's `.dhxml` can name the same parts differently.
QuantAM keeps its own names, so if `Part(1)` was deleted in QuantAM the CSV
runs `Part(2)` to `Part(16)`, while the `.dhxml` numbers the same 15 parts
`1` to `15`. Matching by name would give each part its neighbour's values,
so the import matches each CSV part to the build's part **at the same X/Y
position**. This works with any part assignment (DHXML, Direct or DBSCAN),
and the message after an import says "matched by position" when it did. A
CSV part at no part of the build (a CSV from another build, say) is named in
the message and its values are left out.

## Parts with the same name

If the build contains several parts with the same name, each copy is told
apart by its instance number: `Part(5)#5`, `Part(5)#6`, and so on. Parameters
from the parts CSV are matched to the right copy.

## See also

- [CoV summary](help:plot-cov)
- [Macros](help:macros): part steps are re-read from each build's own CSV.
