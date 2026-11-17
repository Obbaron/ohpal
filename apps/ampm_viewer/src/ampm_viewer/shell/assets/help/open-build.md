---
title: Opening a build
section: Getting started
order: 20
keywords: new, open, recent, favourites, folder, build, load, search, star, single build, info, close, properties
context: file.start, file
---
# Opening a build

A *build* is a folder. Point the app at the folder and it finds what it needs
inside.

## New or Open?

- **New ▸ Single build** (or the **Single build** tile): for a build you have
  not prepared yet. The app detects the build's inputs and takes you to the
  [DataStore setup](help:datastore-setup) page. If the build already has a
  DataStore, you are asked whether to overwrite it; answer no and the existing
  one simply opens.
- **Open**: for a build that already has a DataStore. It opens straight onto
  the Data tab. If there is no DataStore yet, you are offered to create one.

Both open a folder picker: choose the build's folder (the one that contains
the exported packets), not a file inside it.

**New** also makes a [Stacked build](help:stacked-builds) (a build printed in
steps, read as one) and an [Excel template](help:create-excel).

## Info and Close

Once a build is loaded, **Info** in the File tab's sidebar shows its
properties: its type and folder, how many layers are built and the
DataStore's size on disk, the processing it was built with and its inputs.
**Open build folder** shows the folder. **Close** appears on any page other
than the landing page and leads back to it.

## What a build folder contains

| Input | Needed for |
| --- | --- |
| **Packet source**: the folder of exported layer packets | Everything. This is the data. |
| **Parts CSV**: the QuantAM parts export | Part assignment, importing part columns (laser parameters among them), the Excel template. |
| **DHXML**: the `BuildStarted` file | Part assignment by bounding box, the full Excel template. |
| **STL**: the full-plate export | Masking. |

Only the packet source is required. Features that need a missing input are
greyed out, with the reason in their tooltip.

## Recent builds

The list on the File tab's landing page shows the builds and plot library
plots you have opened, newest first, in columns: the **Type** (*Single build*,
*Stacked build* or *Library plot*), whether a build is **ready** (has a
DataStore) or **needs build**, and when it was **Opened**. Double-click a row
to open it.

- Click the **star** on a row to keep it under **Favourites**.
- Type in **Search for a file** to narrow the list by name.
- Builds whose folder (or plots whose file) no longer exists drop off the
  list.

## See also

- [Setting up the DataStore](help:datastore-setup)
- [Stacked builds](help:stacked-builds)
- [Excel template](help:create-excel)
