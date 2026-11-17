---
title: Stacked builds
section: Getting started
order: 35
keywords: stacked, stepped, step, steps, seam, continuous, layers, build time, combine, merge
---
# Stacked builds

A *stepped* build is printed as separate jobs, each on top of the last. Each
step is its own build folder, with its own packets, STL, parts CSV and
.dhxml, and its layers are numbered from 1 again. A **stacked build** reads the
steps together as one continuous build. The step folders are not changed.

## Making one

1. On the File tab, choose **New ▸ Stacked build** (or the **Stacked build**
   tile).
2. **Add step...** for each step's build folder, bottom step first. The list
   shows each step's own layers and where they land in the stack
   (`layers 1-4  ->  401-404`). **Move up** / **Move down** fix the order.
3. Give it a **Name**, and choose the folder to **Keep in**: a new folder,
   outside the steps' folders.
4. **Create**. The stack opens on its [DataStore setup](help:datastore-setup)
   page, like a new build.

The folder holds `stacked.toml` (the name and the steps, with paths relative
to the folder, so the set can move together) and the stack's own settings
and plots. Open it later with **Open** or from the Recent list, like
any build.

## How the steps join up

| Column | In a stacked build |
| --- | --- |
| `layer` | Carries on: the second step's layer 1 follows the first step's last layer. |
| `Z` | Carries on, each step's layers at its own layer thickness. |
| `step` | Which step the row came from (1, 2, ...). |
| `Build time` | Seconds from the start of the first layer, through every layer and step. |
| `Start time` | Unchanged: microseconds from the start of the row's own layer. |
| `part_id` | Takes the step: `S2 Part(3)`. Steps can reuse part names. |

`Build time` puts each layer straight after the one below it: the packets
don't record the time between layers (recoating, or the pause between steps),
so that time isn't counted.

## One setup for every step

The setup page's choices (columns, mask, part assignment, correction) apply to
every step. Each step reads its own inputs:

- **Masking** slices each step's own STL at that step's layers.
- **Part assignment** (Direct or DHXML) uses each step's own parts CSV or
  .dhxml. A part never spans steps.
- **Laser parameters** and **Import parts CSV** read each step's parts CSV.

An input is offered only when every step has one (the setup page says which
step is missing it). Each step keeps the layer thickness in its own
`config.toml`, so the thickness can't be changed here. DBSCAN part assignment
isn't offered for a stacked build.

The steps' DataStores are their own: building the stack builds any step layers
that aren't built yet, and opening a step on its own uses the same layers.

## See also

- [Opening a build](help:open-build)
- [Setting up the DataStore](help:datastore-setup)
- [Parts](help:parts)
