# AMPM Viewer

PyQt6 desktop application for exploring and plotting AMPM (additive-manufacturing process
monitoring) data within the OHPAL ecosystem. It's the interactive front end over the
[`ohpal.ampm`](../../packages/ohpal_ampm/README.md) pipeline: open a build, set up its
DataStore (mask, part assignment, correction), shape the data in a table (calculated and
label columns, filters, parts), plot it (VisPy: scatter, layer, bar, histogram, CoV,
contour, KDE, violin, k-distance), export to Excel, and record macros to repeat the work
on other builds.

- **Distribution:** `ampm-viewer`
- **Import package:** `ampm_viewer`
- **Depends on:** `ohpal-ampm` (pipeline)
- **Version:** `__version__` in `src/ampm_viewer/__init__.py` (the one place to change
  it; `pyproject.toml` reads it from there)

## Running it

From the workspace root, with the environment synced (`just setup` / `uv sync --all-packages`):

```bash
just run                  # uv run ampm-viewer
# equivalently:
uv run ampm-viewer
python -m ampm_viewer   # if running inside an activated venv
```

`ampm-viewer` is the GUI entry point, launching the main window.

## User guide

The guide is built into the app: **Help** in the title bar, or **F1**. Its articles are
Markdown files in `src/ampm_viewer/shell/assets/help/` (see [docs/APP.md](../../docs/APP.md)).

## Unexpected errors

An error the app did not expect no longer closes it. It is written to a report (version,
platform, traceback, recent log) in the app's data folder and shown in a dialog, and the
app keeps running. On Windows the reports are in
`%LOCALAPPDATA%\AMPM\AMPM Viewer\crash-reports` (newest 30 kept), with `fatal.log`
for hard crashes. See `src/ampm_viewer/shell/crash.py`.

## Building the standalone binary

The app compiles a binary executable with [PyInstaller](https://pyinstaller.org/):

```bash
just build               # uv --directory apps/ampm_viewer run pyinstaller app.spec
```

Output is one file, `apps/ampm_viewer/dist/AMPM-Viewer.exe`: everything is inside it
(nothing to ship beside it). It unpacks itself to a temporary folder each time it starts,
so it starts a little slower than an unpacked app would; a DBSCAN job it starts (the same
.exe run with `--dbscan-job`) reuses that unpacked copy. A few layout details that make the
build work:

- **`src/ampm_viewer/__main__.py`** is the entry script. PyInstaller runs it as
  `__main__`, outside the package, so it imports `ampm_viewer.shell.app` absolutely.
- **`app.spec`** must be run from this directory (the `just build` recipe handles that via
  `uv --directory`); its paths are relative to `apps/ampm_viewer/`.
- The lazily-imported pipeline (`ohpal.*`) is pulled in via `collect_submodules`, and the
  app's assets (icons, fonts, help) and VisPy's shaders via `collect_data_files`.
- The executable's icon is `src/ampm_viewer/assets/ampm.ico`; the app also sets it on
  every window at runtime (title bar, taskbar, floating plots, help, log). The .exe's
  Windows file properties (name, version, description) come from `__version__`.

## Layout

```
apps/ampm_viewer/
├── run.py                       # alternative launcher (calls ampm_viewer.main)
├── app.spec                     # PyInstaller build spec
├── pyproject.toml
└── src/
    └── ampm_viewer/
        ├── __init__.py          # __version__
        ├── __main__.py          # entry point: `python -m`, the script, the .exe
        ├── assets/              # app icon (.ico / .icns)
        └── shell/               # the application (see shell/README.md)
            └── assets/          # icons, bundled fonts, help articles
```

## License

All rights reserved.
