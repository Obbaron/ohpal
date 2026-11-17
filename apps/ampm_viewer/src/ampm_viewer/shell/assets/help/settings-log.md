---
title: Settings, status bar and log
section: Reference
order: 10
keywords: settings, options, preferences, theme, dark, light, macro folder, plot library, builds folder, recent, clear, reset, style defaults, ampm folder, status, progress, log, console, export log, background, messages
---
# Settings, status bar and log

## Settings

The **Settings** button (the gear at the top right) opens the Settings
window. Choose a category on the left; its settings are on the right. Nothing
changes until you press **OK**; **Cancel** leaves everything as it was.

- **General**
  - **Appearance**: **Auto (follow the system)**, **Light** or **Dark**. The
    choice is kept for the next start.
  - **Builds folder**: New and Open start in the folder of the build you
    opened last; with no recent build they start in the builds folder:
    **Builds** in the AMPM folder unless you choose another (**Change…**,
    **Open**, **Use the default**).
  - **Recent builds**: **Clear the Recent list** empties the File tab's
    Recent list. Favourites stay.
- **Plots**
  - **Plot library**: the folder frozen plots are saved to and listed from.
    **Change…**, **Open**, **Use the default**. See
    [Plot library](help:plot-library).
  - **Plot style defaults**: how many plot elements start from a style saved
    with **Set as default**. **Reset to the built-in look** forgets them, so
    new plots use the built-in look (open plots keep theirs).
- **Macros**
  - **Macro folder**: where macros are saved and listed from (by default
    `%APPDATA%\AMPM\Macros` on Windows). **Change…**, **Open**, **Use the
    default**. See [Macros](help:macros).
  - **Recent macros**: **Clear the Recent list** empties the Run menu's
    Recent list.
- **Files**: where the app keeps its files, each with **Open**: the AMPM
  folder (`%APPDATA%\AMPM` on Windows: your settings, and by default the
  builds folder, macros, the plot library and crash reports), the crash
  reports, and the settings file, `ampm-viewer.conf`.

## Status bar

The bar along the bottom reports what the app is doing.

- **The message** on the left is the latest result: rows loaded, a column
  added, a file written, or why something did not happen. Hover it to read a
  long message in full.
- **The progress bar** shows while a build, query or export is running.
  During a DataStore build, **Cancel** beside it stops the build after the
  current layer.
- **Background work** that takes a while, such as a DBSCAN part assignment,
  is noted here with how far it has got until it finishes. You can keep
  working meanwhile, or press **Cancel** beside it to stop it.
- **● Recording macro** and a step count show while a
  [macro](help:macros) is being recorded.

## Log

**Show log** at the right end of the status bar opens the log: every status
message of the session, plus the detailed output of building and reading the
data. **Export log** saves it to a text file.

When something fails or takes longer than you expect, the log is the first
place to look, and the file to send when asking for help.
