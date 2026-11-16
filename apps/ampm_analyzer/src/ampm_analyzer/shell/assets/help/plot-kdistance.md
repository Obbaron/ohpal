---
title: K-distance curve
section: Plots
order: 65
keywords: k-distance, kdist, dbscan, eps, radius, min_samples, neighbour, elbow, clustering, tune, part assignment
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

The dashed red line is the XY radius in the plot's settings, labelled with
its value, so you can see at a glance which points it would include.

## Settings

The dialog starts from the build's own DBSCAN settings.

- **X, Y, Z**: the position columns. Choose *None (2D)* for Z to measure
  in the plane only.
- **Neighbour (k)**: which neighbour to measure. Use the *min_samples* you
  give DBSCAN.
- **XY radius (eps)**: DBSCAN's radius in the plane, in mm. It sets the
  dashed line.
- **Z radius**: DBSCAN's radius between layers. Only its ratio to the XY
  radius matters here: Z is stretched by that ratio before distances are
  measured, exactly as DBSCAN does.

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
