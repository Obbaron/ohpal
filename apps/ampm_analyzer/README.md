# AMPM Analyzer

PyQt6 desktop application for exploring and plotting AMPM (additive-manufacturing process
monitoring) data within the OHPAL ecosystem. It's the interactive front end over the
[`ohpal.ampm`](../../packages/ohpal_ampm/README.md) pipeline: open a build, set up its
DataStore (mask, part assignment, correction), shape the data in a table (calculated and
label columns, filters, parts), plot it (VisPy: scatter, layer, bar, histogram, CoV,
contour, KDE, violin, k-distance), export to Excel, and record macros to repeat the work
on other builds.

- **Distribution:** `ampm-analyzer`
- **Import package:** `ampm_analyzer`
- **Depends on:** `ohpal-ampm` (pipeline)
- **Version:** `__version__` in `src/ampm_analyzer/__init__.py` (the one place to change
  it; `pyproject.toml` reads it from there)

## Running it

From the workspace root, with the environment synced (`just setup` / `uv sync --all-packages`):

```bash
just run                  # uv run ampm-analyzer
# equivalently:
uv run ampm-analyzer
python -m ampm_analyzer   # if running inside an activated venv
```

`ampm-analyzer` is the GUI entry point, launching the main window.

## User guide

The guide is built into the app: **Help** in the title bar, or **F1**. Its articles are
Markdown files in `src/ampm_analyzer/shell/assets/help/` (see [docs/APP.md](../../docs/APP.md)).

## Unexpected errors

An error the app did not expect no longer closes it. It is written to a report (version,
platform, traceback, recent log) in the app's data folder and shown in a dialog, and the
app keeps running. On Windows the reports are in
`%LOCALAPPDATA%\AMPM\AMPM Analyzer\crash-reports` (newest 30 kept), with `fatal.log`
for hard crashes. See `src/ampm_analyzer/shell/crash.py`.

## Building the standalone binary

The app compiles a binary executable with [PyInstaller](https://pyinstaller.org/):

```bash
just build               # uv --directory apps/ampm_analyzer run pyinstaller app.spec
```

Output lands in `apps/ampm_analyzer/dist/AMPM-Analyzer/` (a one-folder app: ship the
whole folder). A few layout details that make the build work:

- **`src/ampm_analyzer/__main__.py`** is the entry script. PyInstaller runs it as
  `__main__`, outside the package, so it imports `ampm_analyzer.shell.app` absolutely.
- **`app.spec`** must be run from this directory (the `just build` recipe handles that via
  `uv --directory`); its paths are relative to `apps/ampm_analyzer/`.
- The lazily-imported pipeline (`ohpal.*`) is pulled in via `collect_submodules`, and the
  app's assets (icons, fonts, help) and VisPy's shaders via `collect_data_files`.
- The executable's icon is `src/ampm_analyzer/assets/ampm.ico`.

## Layout

```
apps/ampm_analyzer/
├── run.py                       # alternative launcher (imports ampm_analyzer.__main__)
├── app.spec                     # PyInstaller build spec
├── pyproject.toml
└── src/
    └── ampm_analyzer/
        ├── __init__.py          # __version__
        ├── __main__.py          # entry point: `python -m`, the script, the .exe
        ├── assets/              # app icon (.ico / .icns)
        └── shell/               # the application (see shell/README.md)
            └── assets/          # icons, bundled fonts, help articles
```

## License

All rights reserved.
