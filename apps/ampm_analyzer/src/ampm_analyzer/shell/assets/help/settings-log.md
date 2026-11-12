---
title: Settings, status bar and log
section: Reference
order: 10
keywords: settings, theme, dark, light, status, progress, log, console, export log, background, messages
---
# Settings, status bar and log

## Settings

The **Settings** button at the top right sets the theme: **Auto (system)**,
**Light** or **Dark**.

## Status bar

The bar along the bottom reports what the app is doing.

- **The message** on the left is the latest result: rows loaded, a column
  added, a file written, or why something did not happen. Hover it to read a
  long message in full.
- **The progress bar** shows while a build, query or export is running.
- **Background work** that takes a while, such as a DBSCAN part assignment,
  is noted here until it finishes. You can keep working meanwhile.
- **● Recording macro** and a step count show while a
  [macro](help:macros) is being recorded.

## Log

**Show log** at the right end of the status bar opens the log: every status
message of the session, plus the detailed output of building and reading the
data. **Export log** saves it to a text file.

When something fails or takes longer than you expect, the log is the first
place to look, and the file to send when asking for help.
