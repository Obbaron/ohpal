# AMPM Analyzer User Guide

A desktop GUI for exploring Renishaw 500S AMPM data. It loads a build's packet data, optionally masks it to the
part geometry and assigns each point to a part, lets you build per-part derived
statistics, and renders pluggable plot views.

---

## The workflow at a glance

1. **Config tab**: pick a build, review/adjust settings, click **Load Data**.
2. **Analysis tab**: build derived columns,
   choose a plot view, set its axes/options, click **Plot**.

Your choices are remembered per build, so reopening a build restores where you
left off (see [Saved state](#saved-state)).

---

## Config tab

### Project Root

Click **Browse…** next to *Project Root* and select the build's project folder.
The folder is expected to contain a `config.toml` describing the build; if one
isn't present it is generated.

A `config.toml` looks roughly like:

```toml
[paths]
source = "packets"          # relative or absolute
stl = "parts.stl"
parts_csv = "parts.csv"

[build]
layer_thickness = 0.03

[assignment]
method = "direct"           # or "dbscan"
max_distance_mm = "none"

[clustering]                # used when method = "dbscan"
eps_xy = 0.3
eps_z = 0.06
min_samples = 10
layers_per_chunk = 11
overlap_layers = "auto"

[signals]
columns = ["MeltVIEW melt pool (mean)", "Laser output power (mean)"]
```

`config.toml` is treated as the canonical build definition and is **never
modified** by the GUI; in-app tweaks are stored separately.

### Data source paths (collapsible)

Collapsed by default. Expand it to see the three paths read from `config.toml`
— **Source** (packet-data directory), **STL**, and **Parts CSV** — each with a
**Browse…** button if you need to re-point one for this session.

### Settings

- **Layer thickness (mm)**: physical thickness per layer.
- **Layer range**: *All layers* is checked by default (load the whole build).
  Uncheck it to enable the **From** / **To** selectors. The label shows the
  range actually available in the source (e.g. `Available: 1–434`), and the
  selectors are bounded to it. Loading only a sub-range is the quickest way to
  keep memory and processing time down.
- **Apply mask**: keep only points that fall inside the part geometry for
  their layer (requires the STL).
- **Assign parts**: label each point with the part it belongs to (requires the
  Parts CSV).
- **Method**: how points are assigned to parts:
  - **direct**: nearest-part by distance; set **Max distance (mm)** (or
    `none` for no cap).
  - **dbscan**: cluster points first, then map clusters to parts; exposes
    **EPS_XY**, **EPS_Z**, **Min samples**, **Layers per chunk**, and
    **Overlap layers** (`auto` or an integer).

### Load Data

The button at the bottom enables once a config is loaded and the required paths
are present (STL is only required if *Apply mask* is on; Parts CSV only if
*Assign parts* is on). On click, your inputs are validated first; any invalid
numbers, missing files, or a layer range outside what's available are shown in the log and the load is aborted.

During a load the progress bar tracks the phases (load → mask → assign). The
**first** load of a build (or of a new layer range) builds a Parquet cache and
is slower; later loads of the same selection are faster.

---

## Analysis tab

Appears automatically after a successful load.

### Derived columns

Build per-part statistics from a signal:

1. Choose the **statistic** (coefficient of variation), the **signal** column,
   and the **mode**.
2. Click **Add**. The new column (named like `cov_<mode>_<signal>`) is computed
   and listed, and becomes available as a plot axis.
3. Select a column and click **Remove** to drop it.

### Plotting

1. Pick a **Type**: the available plot views are discovered automatically; a
   short description appears below the selector. (You can add your own. See
   [Adding plot views](#adding-plot-views).)
2. Set the **Axes** and any **Settings** the view exposes (these change with
   the selected view).
3. Click **Plot** (bottom of the tab). Plotting runs in the background with a
   busy indicator; the result opens in the plot window.

---

## Adding plot views

Plot views are pluggable: the app ships with a set of built-in views, and you
can add your own by dropping a `.py` file into one of the folders below. New
views are picked up **without rebuilding the app**. This works in the compiled
executable too, because these folders are read from disk at runtime.

### Where view files go

The app looks in these locations, in increasing priority (a view's `NAME`
decides identity; a higher-priority folder overrides a lower one, and any of
them can override a built-in of the same name):

1. **User views folder** (lowest): shared across every build. Created for you
   on first launch:
   - Windows: `%APPDATA%\AMPM\views`
   - macOS: `~/Library/Application Support/AMPM/views`
   - Linux: `$XDG_DATA_HOME/AMPM/views` (or `~/.local/share/AMPM/views`)
2. **Per-build**: `<project_root>/views/`, for views specific to one build.
3. **`AMPM_VIEWS_PATH`** (highest): one or more folders set in this environment
   variable (separated by `;` on Windows, `:` elsewhere). If you list several,
   earlier entries win.

### Reloading

After adding, editing, or removing a view file, click **Reload Views** (next to
the *Type* selector) to re-scan all the folders without restarting. New views
also appear automatically the next time you launch the app, and a build's own
`views/` folder is re-scanned whenever you select that build. Any file that
fails to import or doesn't match the required structure is skipped, with a note
in the log.

### What a view file must contain

A view module must define:

```python
NAME = "My View"                       # shown in the Type dropdown
DESCRIPTION = "What this view shows."  # shown under the selector

AXES = {  # column pickers shown for this view
    # ...
}
SETTINGS = {  # extra option widgets (may be empty)
    # ...
}

def run(df, config, axes, settings):
    # df       : the loaded (masked / part-assigned) data
    # axes     : the columns the user picked for AXES
    # settings : the values the user chose for SETTINGS
    ...
```

The easiest way to start is to copy a built-in view (for example
`ampm/views/scatter_2d.py`) and adapt it; that shows the exact shape of `AXES`
and `SETTINGS`. Files whose name starts with `_` are ignored.

> **Note for the compiled app:** a dropped-in view can use anything already
> bundled in the executable (the `ampm` package, `polars`, `numpy`, the
> plotting stack, …), but it can't pull in a third-party library that wasn't
> bundled. To use additional third-party libraries, recompile the app binary.

---

## Saved state

The app remembers the analysis tab **per build** in a sidecar file, `.ampm-ui.json`, in the build's
project root (separate from `config.toml`, and outside `.cache/` so clearing
the cache never wipes it). It captures:

- your pipeline tweaks (method, layer range, mask/assign toggles, distance and
  clustering parameters, layer thickness), and
- your analysis setup — the *recipe* for each derived column (statistic,
  signal, mode), plus the selected view, axes, and settings.

It autosaves after a load, after adding/removing a derived column, after a
successful plot, and on close.

When you reopen a build, your pipeline tweaks are applied to the Config tab
immediately. After you click **Load Data**, the derived columns are recomputed
and the view/axes/settings are restored — but a plot is **not** drawn
automatically; click **Plot** when ready. Anything that no longer fits the
current build (a signal that's gone, a view that no longer exists, a saved
range wider than what's now available) is skipped or clamped, with a note in
the log.

---

## Caching

Heavy results are cached under `<source>/.cache/`:

- Converted packet data (one Parquet file per layer).
- The mask "keep" result and cluster labels.

Caches are keyed to what produced them, including the layer range. Loading the
full build uses the standard cache files; loading a sub-range writes
range-specific files (e.g. `mask_keep_L00101-00434.pq`) so switching between
ranges reuses prior work instead of recomputing. Changing a parameter that
affects a cache (range, STL, clustering settings, …) recomputes it
automatically — you'll see a "computing fresh…" note in the log rather than an
error.

To force everything to rebuild, delete the `.cache/` folder. Your analysis
setup (`.ampm-ui.json`) is **not** in `.cache/`, so it survives.

---

## Troubleshooting

| Symptom | Likely cause / fix |
| --- | --- |
| **Load Data** stays disabled | No config loaded yet, or a required path is missing (STL with *Apply mask* on, or Parts CSV with *Assign parts* on). |
| "Cannot load - please fix…" in the log | A field failed validation (bad number, missing file, range outside available). Fix the listed item and retry. |
| Analysis tab didn't appear | The load failed. Check the log for the error. |
| Load is very slow the first time | First-time Parquet cache build for that build/range. Subsequent loads are fast. |
| A remembered layer range came back smaller | It was clamped to the layers available in the build you opened. |
| An additional view doesn't appear | Click **Reload Views** and check the log. The file may have failed to import or be missing `NAME`/`AXES`/`SETTINGS`/`run`. Files starting with `_` are ignored. |
| Last folder not remembered after an update | The app's stored-settings key changed; pick a folder once and it's remembered again. |
