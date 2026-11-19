---
title: K-distance curve
section: Plots
order: 65
keywords: k-distance, kdist, dbscan, eps, radius, min_samples, neighbour, elbow, knee, kneedle, slope, derivative, hover, clustering, tune, part assignment
context: plot.K-Distance Curve
---
# K-distance curve

A tuning aid for **DBSCAN** part assignment. DBSCAN groups points that have
at least *min_samples* neighbours within a radius, *eps*. This curve shows
which radius that takes, so you can check the build's settings or choose
better ones.

## What it shows

For a sample of points, the distance to each point's *k*-th nearest
neighbour, sorted from smallest to largest. A point whose *k*-th neighbour is
closer than eps counts as part of a cluster.

- A **flat stretch** is the typical spacing of the scan: most points sit at
  about this distance from their neighbours.
- A **sharp rise** at the right (the elbow) is where sparse and stray points
  begin.

Choose **eps a little above the flat part and below the elbow**: large
enough that the parts' points join up, small enough that stray points stay
out.

## The knee

The app finds the knee for you: a red dot on the curve and a dashed line
across at its distance, labelled with the radii it suggests, for example
**knee: eps XY ≈ 0.164 mm, Z ≈ 0.0329 mm**. It is found with the *Kneedle*
method: with both axes scaled to
0 to 1, the knee is the point furthest below a straight line from the first
point to the last. A few stray points that sit far from the rest don't move
it: it stays where the curve leaves the scan's spacing.

It is only a starting point. A curve with several steps (scan spacings that
differ, for example contours and infill) may have its knee at the first step
of the rise, when a slightly larger eps would keep those points in their
parts. Hover the curve to see how steep it is where, and choose with your
knowledge of the build. **Knee line** on the toolbar hides the line.

## Two radii from one curve

DBSCAN on the position has two radii, eps XY and eps Z, but the curve has one
distance. Before measuring, Z is stretched by eps XY / eps Z (the radii in the
plot's settings, 0.3 and 0.06 mm by default, so Z counts five times), which
turns DBSCAN's reach into a sphere. So a distance *d* on the curve stands for
**eps XY = d** and **eps Z = d × eps Z / eps XY**: a pair of radii in the
ratio you set. The knee's label and the hover give both. To try another
ratio, make the plot again with other radii in its settings. Without Z (2D)
there is only eps XY.

## Hovering

Hover the curve to see the point under the pointer, as on a scatter plot:

- the **radii** its distance stands for: eps XY and eps Z,
- the share of points that have **k neighbours in reach** at those radii:
  DBSCAN's core points. The rest are either at the edge of a cluster or
  noise. Move along the curve to see what a larger or smaller eps takes in,
- its **rank** among the points (smallest distance first),
- the curve's **slope** there: how fast the distance grows, in mm per 1,000
  points, measured over the 0.5% of points on each side. In brackets, how
  that compares with the curve's average slope: "flat" on the flat stretch,
  several times the average past the knee.

## Settings

The dialog starts from the build's DBSCAN settings: the ones on the
DataStore setup page, which come from `config.toml` until you change them
there. Once you have chosen values here, enter them on the setup page and
rebuild.

- **X, Y, Z**: the position columns. Choose *None (2D)* for Z to measure
  in the plane only.
- **Neighbour (k)**: which neighbour to measure. Use the *min_samples* you
  give DBSCAN.
- **XY radius (eps)** and **Z radius**: only their ratio matters here. Z is
  stretched by it before distances are measured, exactly as DBSCAN does,
  and the radii the curve suggests keep it (see *Two radii from one curve*).

## How it is measured

Up to 50,000 points are sampled for the curve, but their neighbours are
searched among **every** point of the plot's layers. The app's DBSCAN
clusters the full data, and a sparser sample would make every distance look
several times larger than DBSCAN sees it. (The library's
`k_distance_curve` searches only within its sample, so its curve sits higher
than this one.)

## See also

- [Setting up the DataStore](help:datastore-setup): where DBSCAN is chosen.
- [Parts](help:parts)
