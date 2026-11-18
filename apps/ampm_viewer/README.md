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
platform, traceback, recent log) in the AMPM folder and shown in a dialog, and the
app keeps running. The reports are in `crash-reports` there (newest 30 kept), with
`fatal.log` for hard crashes. See `src/ampm_viewer/shell/crash.py`.

The **AMPM folder** holds what the app keeps: its settings (`ampm-viewer.conf`),
`Builds` (the default builds folder), `Macros`, `Plots` (the plot library) and
`crash-reports`. It is `%APPDATA%\AMPM` on Windows,
`~/Library/Application Support/AMPM` on macOS and `$XDG_DATA_HOME/AMPM`
(`~/.local/share/AMPM`) on Linux; set `AMPM_DATA_DIR` to use another folder. See
`settings.data_dir` in `src/ampm_viewer/shell/settings.py`.

## Building the app and its installers

The app is compiled with [PyInstaller](https://pyinstaller.org/), then packed
into an installer:

```bash
just build               # uv --directory apps/ampm_viewer run pyinstaller --noconfirm app.spec
just installer           # build, then installer/build_installer.py
```

`just build` makes a folder, `apps/ampm_viewer/dist/ampm-viewer-v<version>-<arch>/`
(for example `ampm-viewer-v2.0.1-x64`; `arm64` when built with an Arm Python),
holding `AMPM Viewer.exe` and its `_internal` folder of libraries and data. It runs
where it is. A folder starts in a fraction of the time the one-file .exe of 2.0.0 took,
which unpacked all of itself (about 550 MB) to a temporary folder at every start. A
DBSCAN job the app starts is the same program run with `--dbscan-job`. On macOS the
build also makes `dist/AMPM Viewer.app`.

`just installer` then makes, beside it:

- **Windows:** `ampm-viewer-v<version>-<arch>-setup.exe`, with
  [Inno Setup](https://jrsoftware.org/isinfo.php) 6.3 or later
  (`winget install JRSoftware.InnoSetup`; `ISCC.exe` is found on the PATH, in the
  `ISCC` variable, or where Inno Setup installs itself). The script is
  `installer/ampm-viewer.iss`. The setup installs for the current user, without
  administrator rights, to `%LOCALAPPDATA%\Programs\AMPM Viewer`; a new version
  replaces the old one in place (same Start-menu shortcut and taskbar pin). It adds a
  Start-menu shortcut, a desktop shortcut if ticked, opens `.ampmplot` files with the
  app if ticked (on by default), and offers to start the app. Uninstalling leaves
  settings, macros and plots (`%APPDATA%\AMPM`) alone.
- **macOS:** `ampm-viewer-v<version>-<arch>.dmg`, made with the system's `hdiutil`:
  open it and drag AMPM Viewer to Applications. Built on an Apple silicon Mac
  (arm64). The app is signed ad hoc, not by a Developer ID, so macOS stops its first
  start. On macOS 15 and later: try to open it, then System Settings > Privacy &
  Security > **Open Anyway**. On macOS 14 and earlier: Control-click the app, choose
  **Open**, then **Open**. Set `AMPM_CODESIGN_IDENTITY` to a Developer ID to sign it
  properly (notarising is not scripted yet).

Double-clicking a `.ampmplot` opens it in the AMPM Viewer already running (a second
start hands the file over and quits; `shell/single_instance.py`), or starts the app
with it. A start without a file always opens a new window.

The build's names (version, architecture, folder and program names) come from
`build_names.py`, shared by `app.spec` and the installer script. A few layout details
that make the build work:

- **`src/ampm_viewer/__main__.py`** is the entry script. PyInstaller runs it as
  `__main__`, outside the package, so it imports `ampm_viewer.shell.app` absolutely.
- **`app.spec`** must be run from this directory (the `just build` recipe handles that via
  `uv --directory`); its paths are relative to `apps/ampm_viewer/`.
- The lazily-imported pipeline (`ohpal.*`) is pulled in via `collect_submodules`, and the
  app's assets (icons, fonts, help) and VisPy's shaders via `collect_data_files`.
- The executable's icon is `src/ampm_viewer/assets/ampm.ico` (`ampm.icns` on macOS);
  the app also sets it on every window at runtime (title bar, taskbar, floating plots,
  help, log). The .exe's Windows file properties (name, version, description) come
  from `__version__`.

## Layout

```
apps/ampm_viewer/
├── run.py                       # alternative launcher (calls ampm_viewer.main)
├── app.spec                     # PyInstaller build spec
├── build_names.py               # version, architecture and file names of a build
├── installer/                   # ampm-viewer.iss (Windows), build_installer.py
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
