---
title: DBSCAN clusters
section: Data
order: 45
keywords: dbscan, cluster, clusters, clustering, group, density, noise, outlier, spatter, hot spot, neighbour, radius, eps, min samples, chunk, layers per chunk, overlap, position, feature
---
# DBSCAN clusters

**DBSCAN clusters** on the Data toolbar groups the points into clusters and
adds a column naming each point's cluster. It is the same DBSCAN the
DataStore can use to assign parts, but for anything: hot spots in the melt
pool, a patch of spatter, points that sit apart from the rest.

## How DBSCAN groups points

Two points are **neighbours** when they are within every radius of each
other. A point with at least **min samples** neighbours is in a dense region
and starts (or joins) a cluster, and the cluster grows through every
neighbour that is dense too. A point that is in no cluster is **noise**.

There is no number of clusters to choose: DBSCAN finds as many as the data
holds, of any shape.

## What it clusters on

- **Position** (on at the start): X, Y and Z, with an **XY radius** and a
  **Z radius** in mm. Points close together on the plate and over a few
  layers group together.
- **Other columns**: press **Add column** for each numeric column to
  cluster on, each with its own **radius** in that column's units. A
  starting radius is suggested (a twentieth of the column's usual spread).
  The ✕ removes one.

Use either or both. With both, points must be close in place *and* in every
added column: for example the position plus the melt pool, with a melt pool
radius of 50, finds places where hot points sit together.

## Which rows

DBSCAN clusters **the rows the filters keep, in every built layer**, not only
the layer on screen. Rows a filter leaves out get no cluster (an empty
cell). Set the [filters](help:filters) first, for example a melt pool
threshold to cluster only the hot points.

## Running it

**Run** starts it in the background: its progress is in the status bar, with
**Cancel**, and you can carry on working. When it is done the column is
added, and the [log](help:settings-log) says what it found: how many
clusters, how much noise and the sizes of the largest.

The column is text: **1** is the largest cluster, **2** the next and so on,
then **noise**. Colour a scatter plot by it, use it as a bar chart's
category, or filter on it (`[cluster] == "1"`). It follows the layer you show
and survives renames, and **Undo** removes it in one step.

## Chunks (position only)

A whole build is too many points to cluster at once, so with the position
it goes a few layers at a time:

- **Layers per chunk**: how many layers are clustered at once. Fewer use
  less memory; the default is `config.toml`'s.
- **Overlap layers**: how many layers neighbouring chunks share, so a
  cluster that crosses a chunk's edge stays one cluster. **Auto** uses the
  least the Z radius needs (twice the layers the Z radius spans, at least
  2). It must be less than the layers per chunk.

Without the position, the values alone are clustered in one go, on a
representative sample of up to 200,000 rows; every other row then takes the
cluster of its nearest sampled row (or noise, if that is further than the
radii). In very dense data a smaller sample is used to keep memory in hand,
and min samples is scaled with it.

## Choosing the settings

- Start from the radius of the effect you are after: the size of a hot spot
  in mm, or the difference in a value that counts as "the same".
- Too many small clusters, or much noise: raise the radii or lower min
  samples. One big cluster: lower the radii or raise min samples.
- The [K-distance curve](help:plot-kdistance) helps choose the XY radius.

## In a macro

A recorded macro keeps the settings, not the result: when it runs it
clusters again on the build it runs on, and waits for the clustering to
finish (with a small progress window and **Cancel**) before the next step.
See [Macros](help:macros).
