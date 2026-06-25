# AMPM Analyzer

PyQt6 desktop application for exploring and plotting AMPM (additive-manufacturing process
monitoring) data within the OHPAL ecosystem. It's the interactive front end over the
[`ohpal.ampm`](../../packages/ohpal_ampm/README.md) pipeline: load a build's monitoring
data, run it through the pipeline, and visualize the result through a library of plot
"views".

- **Distribution:** `ampm-analyzer`
- **Import package:** `ampm_analyzer`
- **Depends on:** `ohpal-ampm` (pipeline)

## Running it

From the workspace root, with the environment synced (`just setup` / `uv sync --all-packages`):

```bash
just run                  # uv run ampm-analyzer
# equivalently:
uv run ampm-analyzer
python -m ampm_analyzer   # if running inside an activated venv
```

`ampm-analyzer` is the GUI entry point, launching the main window.

## Views

Plot types are **views** - small modules that each declare `NAME`, `AXES`, `SETTINGS`, and
`run(df, config, axes, settings)` function. The app discovers them at runtime, so new plot
types can be added dynamically:

1. **Built-in views**, shipped inside the package at `src/ampm_analyzer/views/`.
2. **External drop-in views**, loaded from disk in order of precedence:
   - **User data dir** (shared across builds):
     - Windows: `%APPDATA%\AMPM\views`
     - macOS: `~/Library/Application Support/AMPM/views`
     - Linux: `$XDG_DATA_HOME/AMPM/views` (or `~/.local/share/AMPM/views`)
   - **Per-build:** `<project_root>/views/`
   - **`AMPM_VIEWS_PATH`** (highest): an `os.pathsep`-separated list of directories.

To add a view, drop a `.py` file defining the four required attributes into one of those
directories.

## Building the standalone binary

The app compiles a binary executable with [PyInstaller](https://pyinstaller.org/):

```bash
just build               # uv --directory apps/ampm_analyzer run pyinstaller app.spec
```

Output lands in `apps/ampm_analyzer/dist/ampm-analyzer/`. A few layout details that make
the build work:

- **`run.py`** is the PyInstaller entry point; a thin launcher *outside* the package. It
  exists because PyInstaller runs its entry script as `__main__`, where the package's
  relative imports wouldn't resolve; `run.py` imports `ampm_analyzer.__main__:main` so the
  real code always runs as a proper package submodule.
- **`app.spec`** must be run from this directory (the `just build` recipe handles that via
  `uv --directory`); its paths are relative to `apps/ampm_analyzer/`.
- Built-in views and the lazily-imported pipeline are pulled in via `collect_submodules`
  in the spec since neither is visible to PyInstaller's static analysis.

## Layout

```
apps/ampm_analyzer/
├── run.py                       # PyInstaller launcher (outside the package)
├── app.spec                     # PyInstaller build spec
├── pyproject.toml
└── src/
    └── ampm_analyzer/
        ├── __init__.py
        ├── __main__.py          # shared entry point: `python -m`, the script, run.py
        ├── main.py              # the application
        ├── assets/              # icons (shipped as package data)
        └── views/               # built-in plot views
```

## License

All rights reserved.
