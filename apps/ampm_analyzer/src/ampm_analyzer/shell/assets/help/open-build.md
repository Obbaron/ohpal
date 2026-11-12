---
title: Opening a build
section: Getting started
order: 20
keywords: new, open, recent, favourites, folder, build, load, search, star
context: file.start, file
---
# Opening a build

A *build* is a folder. Point the app at the folder and it finds what it needs
inside.

## New or Open?

- **New**: for a build you have not prepared yet. The app detects the build's
  inputs and takes you to the [DataStore setup](help:datastore-setup) page. If
  the build already has a DataStore, you are asked whether to overwrite it;
  answer no and the existing one simply opens.
- **Open**: for a build that already has a DataStore. It opens straight onto
  the Data tab. If there is no DataStore yet, you are offered to create one.

Both buttons open a folder picker: choose the build's folder (the one that
contains the exported packets), not a file inside it.

## What a build folder contains

| Input | Needed for |
| --- | --- |
| **Packet source**: the folder of exported layer packets | Everything. This is the data. |
| **Parts CSV**: the QuantAM parts export | Part assignment, laser parameters, importing part columns, the Excel template. |
| **DHXML**: the `BuildStarted` file | Part assignment by bounding box, the full Excel template. |
| **STL**: the full-plate export | Masking. |

Only the packet source is required. Features that need a missing input are
greyed out, with the reason in their tooltip.

## Recent builds

The list on the Start page shows the builds you have opened, newest first, and
whether each is **ready** (has a DataStore) or **needs build**. Double-click a
row to open it.

- Click the **star** on a row to keep it under **Favourites**.
- Type in **Search for a file** to narrow the list by name.
- Builds whose folder no longer exists drop off the list.

## See also

- [Setting up the DataStore](help:datastore-setup)
- [Create Excel from AMPM](help:create-excel)
