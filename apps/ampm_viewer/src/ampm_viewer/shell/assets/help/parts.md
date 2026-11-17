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

## Add laser parameters

Adds the laser parameters each part was built with as columns, read from the
build's parts CSV: hatch power, point distance, exposure time, the derived
**Hatch Speed** and the rest of the numeric scan-volume settings.
The message afterwards says how many of the build's parts were matched.

These columns make parameter studies possible: plot the mean melt pool per
part against hatch speed and power in a [contour plot](help:plot-contour).

## Import parts CSV

Opens the parts CSV section by section (Parent Parts, Strategy, Scan
Volume, …). Tick the columns you want from any section; the count at the
bottom shows how many are staged. **Import** adds them all in one step.

Both this and **Add laser parameters** need the parts CSV; without one they
are greyed out.

## Parts with the same name

If the build contains several parts with the same name, each copy is told
apart by its instance number: `Part(5)#5`, `Part(5)#6`, and so on. Parameters
from the parts CSV are matched to the right copy.

## See also

- [CoV summary](help:plot-cov)
- [Macros](help:macros): part steps are re-read from each build's own CSV.
