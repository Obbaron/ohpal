# AMPM Viewer: the application

The app itself (PyQt6 + VisPy). `ampm_viewer.__main__` and the packaged
executable both start it through `app.main()`.

## Run

```
python -m ampm_viewer            # or: uv run ampm-viewer / just run
python -m ampm_viewer.shell      # the same app
```

## How it fits together

- **`controller.py`** is the bridge between the widgets and `ohpal`: it opens
  builds, runs every query and long job on a worker thread (`workers.py`), and
  owns the per-build state (`state.py`, `uistate.py`).
- **`actions.py`** is the single entry point for anything that changes the
  data's shape or view; it feeds undo / redo (`history.py`) and macro recording
  (`macros.py`).
- **Plots** are described by a `PlotSpec` (`plotspec.py`), turned into arrays
  by `plotdata.py` (pure, no Qt), drawn by `plot_tab.py` (VisPy), and offer the
  toolbar controls declared in `plotcontrols.py`.
- **Unexpected errors** go to `crash.py`: a report file plus a dialog, and the
  app keeps running.

## Files

| File | What it is |
| --- | --- |
| `app.py` | Entry point: QApplication, theme, log capture, crash handler, main window |
| `window.py` | Main window: tab row (doubles as the title bar), context toolbar, side panel, status bar |
| `titlebar.py` | The frameless window's title bar, window buttons and resize grips |
| `backstage.py` | File tab: open / new build, recent builds, Create Excel |
| `datastore_settings.py` | DataStore setup page (mask, part assignment, correction, columns) |
| `data_tab.py`, `grid_model.py` | Data tab: the virtualised grid over a Polars frame |
| `toolbars.py` | The Data and Plot toolbars (the Plot one is built from a plot's controls) |
| `dock.py` | Side panel: column info, plot appearance, plot-element editor |
| `controller.py`, `workers.py` | Build loading, queries and long jobs, off the UI thread |
| `state.py`, `uistate.py`, `recents.py` | Session state, per-build UI state, recent builds |
| `actions.py`, `history.py`, `macros.py`, `macro_dialog.py` | Actions, undo / redo, macros |
| `derive.py`, `colref.py` | The column formula language and rename-aware column references |
| `derive_dialog.py`, `derive_editor.py`, `label_dialog.py`, `filter_dialog.py` | Calculated column, label, and filter dialogs (with the formula editor) |
| `part_calc_dialog.py`, `import_parts_dialog.py` | Parts: per-part calculation, parts CSV import |
| `excel_dialog.py`, `export.py`, `export_dialog.py` | Add a column from Excel; export to Excel |
| `plot_dialog.py` | New-plot dialog |
| `plotspec.py`, `plotdata.py`, `plotcontrols.py` | What a plot is, its data, its toolbar controls |
| `plot_tab.py`, `plot_window.py`, `plot_elements.py` | Drawing a plot, a popped-out plot, editable plot text |
| `help.py`, `help_window.py` | The in-app guide (articles in `assets/help`) |
| `crash.py` | Unexpected errors: report file + dialog |
| `logconsole.py` | Captured console output and the log window |
| `message_dialog.py`, `card.py`, `widgets.py` | Shared dialog and widget helpers |
| `icons.py`, `theme.py` | Carbon icons (tinted per theme) and light / dark theming |

## Assets

- `assets/icons/carbon`: IBM Carbon icons (Apache 2.0, licence alongside).
- `assets/fonts`: Liberation Sans / Serif / Mono for plot text (SIL OFL 1.1,
  licence alongside).
- `assets/help`: the help articles (Markdown with a small front-matter block).
