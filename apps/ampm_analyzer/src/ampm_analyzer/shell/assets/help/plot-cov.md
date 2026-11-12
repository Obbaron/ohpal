---
title: CoV summary
section: Plots
order: 50
keywords: cov, coefficient of variation, stability, variability, overall, per layer, across layers, drift, summary
context: plot.CoV Summary
---
# CoV summary

The coefficient of variation (CoV) is the standard deviation divided by the
mean. It has no units, so it compares how *steady* a signal is between parts
that run at very different levels.

A CoV Summary draws one bar per group, over the whole build.

- **Group by**: what each bar is, usually `part_id`.
- **Signal**: the column to measure.
- **Mode**: which kind of variation to measure.

## Modes

| Mode | What it measures |
| --- | --- |
| **overall** | All of a group's points together. Total variability: scatter within layers, drift between layers and outliers all count. |
| **per_layer_mean** | The CoV within each layer, averaged over the layers. Stability *within* a layer, ignoring drift from layer to layer. |
| **across_layers** | The CoV of the layer averages. Drift *between* layers. Good for finding parts where the process slowly walks off target. |

A group whose mean is essentially zero has no meaningful CoV, so it shows no
value.

## The same numbers as columns

To use a CoV in other plots or an export, add it as a column with
[Parts ▸ Per-part calculation](help:parts) or a formula such as
`cov([Meltpool]) by [part_id]`. Per layer, group by both:
`cov([Meltpool]) by [part_id, layer]`.
