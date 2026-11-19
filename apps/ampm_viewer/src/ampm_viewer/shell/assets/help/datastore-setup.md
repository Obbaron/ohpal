---
title: Setting up the DataStore
section: Getting started
order: 30
keywords: datastore, build, rebuild, setup, layers, thickness, columns, rename, mask, masking, correction, part assignment, direct, dhxml, dbscan, eps, radius, min samples, chunk, overlap, max distance, part filter, browse, inputs, cancel, stop, cache, required
context: file.datastore
---
# Setting up the DataStore

The DataStore is a fast, per-layer copy of the build's packet data. You build
it once; after that the build opens in seconds. The setup page decides what
goes into it and how the data is prepared.

Reach it with **New ▸ Single build**, or with the **DataStore** button on the
File tab once a build is loaded. Click a group's title (**Build inputs**,
**Layers**, **Columns**, **Processing**) to fold it away; they start open.

## Build inputs

What was found in the build folder: the packet source, the DHXML, the STL and
the parts CSV. Anything shown as *not found* switches off the options that
depend on it. **Browse...** beside an input picks it yourself; the choice is
saved in the build's `config.toml`, so it stays. A new packet source reloads
the build, since its layers and columns come from the packets. (A stacked
build's inputs are each step's own, so they are chosen in the step's build.)

## Layers

- **Thickness (mm)**: the layer thickness, detected from the build and
  editable. The **Z** column is the layer number times this value.
- **All layers**: converts every layer (the default). Untick it to choose a
  range with **From** and **To**; **Available** shows the layers the build has.

## Columns

Tick the columns you want to load, and type a new name on the right of any you
want renamed. A new build starts with a default set already ticked and
renamed (for example *MeltVIEW melt pool (mean)* becomes *Meltpool*).
[About the data](help:about-data) explains what each column is.

- **All** / **None** tick every column, or only the required ones.
- **Default** goes back to the default set and renames.
- **Clear renames** removes every rename.

The columns at the bottom of the list are **required** and always load:
position (*Demand X*, *Demand Y*), *Start time*, *layer*, *Z* and
*LaserVIEW (mean)*. You can still rename them.

## Processing

- **Apply mask**: keeps only the points that fall inside the part outlines of
  the STL, layer by layer. Layers with no part in them end up with no data and
  are skipped by the layer selector. Needs the STL.
- **Assign parts**: adds a `part_id` column saying which part each point
  belongs to. Choose how:
  - **Direct**: each point goes to the nearest part centre in the parts CSV.
    Fast; the usual choice. **Max distance (mm)** leaves a point without a
    part when it is further than this from every part centre (*No limit*:
    every point joins its nearest part).
  - **DHXML**: each point goes to the part whose bounding box contains it.
  - **DBSCAN**: clusters the points themselves and matches each cluster to a
    part. It is computationally expensive and takes a while on a full build.
    It runs in the background after the build opens: you can work meanwhile,
    and the part column appears when it finishes. The status bar shows how far
    it has got, with **Cancel** to stop it. The result is saved with the
    build and used again, by reopening or by a rebuild, for as long as what it
    was made from is unchanged: the layers and their data files, the parts
    CSV, the STL (both by their content, so moving the build doesn't matter)
    and the settings below. A rebuild for anything else (columns, correction,
    renames) keeps it. Its settings appear when you choose it:
    - **XY radius (mm)**: how close points must be in the plane to count as
      neighbours (DBSCAN's *eps*).
    - **Z radius (mm)**: the same between layers.
    - **Min samples**: how many neighbours a point needs within the radius to
      start or grow a cluster.
    - **Layers per chunk**: the build is clustered a chunk of layers at a
      time. Fewer layers use less memory; more run faster.
    - **Overlap chunks**: how many layers each chunk shares with the next, so
      clusters join up across chunks. *Auto* shares just enough for the Z
      radius.

    They start from the build's `config.toml` and are kept with the build.
    Changing them means a rebuild, which clusters again. A
    [K-distance curve](help:plot-kdistance) helps choose the radius.
  - **Part filter** (fold it open): the parts to keep in the DataStore, all
    ticked to start with. Each part shows where it sits, its centre's X and Y
    in mm (`Part(1) @ -26.8 -11.6`). Untick a part, or use **All** / **None**, and its
    points are left out of the data; points with no part stay. The choice is
    kept with the build.
- **Apply correction**: removes the position-dependent bias of the MeltVIEW
  melt-pool signal. It is calibrated for the **MAIN** machine and the
  *MeltVIEW melt pool (mean)* column only. **Output**: **Override column**
  writes over the original; **New column** writes the result beside it, under
  the name you type.

## Build, rebuild, cancel

**Build DataStore** converts the chosen layers; progress shows in the status
bar. **Cancel** on this page returns to the File tab's landing page without
changing anything.

To stop a build that is running, press **Cancel** beside the progress bar. It
stops after the layer it is on and brings you back here with your choices as
they were. The layers already converted are kept, so building again carries
on from there (a rebuild starts over).

On a build that already has a DataStore the button reads **Rebuild
DataStore**. A rebuild is a clean slate: your column changes, filters, layout
and open plots for that build are discarded and the data is converted again.
A saved DBSCAN part assignment is kept when its inputs are unchanged (see
above).

When the build finishes you land on the Data tab, on the lowest layer that has
data.

## See also

- [Opening a build](help:open-build)
- [Parts](help:parts)
- [When something goes wrong](help:troubleshooting)
