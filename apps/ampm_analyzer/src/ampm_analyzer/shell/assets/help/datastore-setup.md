---
title: Setting up the DataStore
section: Getting started
order: 30
keywords: datastore, build, rebuild, setup, layers, thickness, columns, rename, mask, masking, correction, part assignment, direct, dhxml, dbscan, cache, required
context: file.datastore
---
# Setting up the DataStore

The DataStore is a fast, per-layer copy of the build's packet data. You build
it once; after that the build opens in seconds. The setup page decides what
goes into it and how the data is prepared.

Reach it with **New**, or with the **DataStore** button on the File tab once a
build is loaded.

## Build inputs

The top box shows what was found in the build folder: the packet source, the
DHXML, the STL and the parts CSV. Anything shown as *not found* switches off
the options that depend on it.

## Layers

- **Range**: the layers to convert. It starts at the build's full extent.
- **Thickness**: the layer thickness in mm, detected from the build and
  editable. The **Z** column is the layer number times this value.

## Columns

Tick the columns you want to load, and type a new name on the right of any you
want renamed. A new build starts with a default set already ticked and
renamed (for example *MeltVIEW melt pool (mean)* becomes *Meltpool*).
[About the data](help:about-data) explains what each column is.

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
    Fast; the usual choice.
  - **DHXML**: each point goes to the part whose bounding box contains it.
  - **DBSCAN**: clusters the points themselves and matches each cluster to a
    part. It is computationally expensive and takes a while on a full build.
    It runs in the background after the build opens: you can work meanwhile,
    and the part column appears when it finishes. The result is saved, so
    reopening the build is instant.
- **Apply correction**: removes the position-dependent bias of the MeltVIEW
  melt-pool signal. It is calibrated for the **MAIN** machine and the
  *MeltVIEW melt pool (mean)* column only. Write the result to a **New column**
  (give it a name) or **Override** the original.

## Build, rebuild, cancel

**Build DataStore** converts the chosen layers; progress shows in the status
bar. **Cancel** returns to the Start page without changing anything.

On a build that already has a DataStore the button reads **Rebuild
DataStore**. A rebuild is a clean slate: your column changes, filters, layout
and open plots for that build are discarded and the data is converted again.

When the build finishes you land on the Data tab, on the lowest layer that has
data.

## See also

- [Opening a build](help:open-build)
- [Parts](help:parts)
- [When something goes wrong](help:troubleshooting)
