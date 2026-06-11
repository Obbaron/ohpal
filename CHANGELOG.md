# Changelog

All notable changes to AMPM Analyzer are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.2] - 2026-06-11

### Fixed

- 3D scatter no longer fails with a Plotly `ValueError` ("Invalid element(s)
  received for the 'color' property") when the selected color column contains
  nulls — e.g. coloring by a per-part statistic while some rows are
  unassigned (`noise`). Null-colored points are now excluded from the plot
  with a logged count, and an explicit error is raised if *every* sampled
  point has a null color.
- Plotting no longer requires `part_id` to exist. Hover columns are now
  best-effort across all views (3D scatter, 2D scatter, contour, and the
  layered viewer): columns missing from the data — such as `part_id` when
  part assignment is skipped at import — are omitted from the hover tooltip
  with a logged note instead of raising `KeyError`. Missing axis or color
  columns still fail loudly.

### Changed

- `stl_stream.py` docstrings reformatted to the numpy convention, with full
  `Parameters`/`Returns`/`Raises` sections added to all helpers (no behavior
  change; verified against a known build).

## [1.1.1] - 2026-06-04

### Changed

- Reverted distribution from the single self-contained executable (one-file
  PyInstaller build, introduced in 1.1.0) back to a folder build: a smaller
  executable alongside an `_internal` folder.

## [1.1.0] - 2026-06-04

### Added

- Drop-in plot views. Additional views are loaded at runtime from three
  locations, in increasing precedence: a per-user views folder, a build's
  `<project_root>/views/` folder, and the `AMPM_VIEWS_PATH` environment
  variable. Any external view may override a built-in of the same name. Works
  in the compiled executable without rebuilding. Documented in `docs/APP.md`.
- **Reload Views** button (next to the plot *Type* selector) to re-scan the
  view folders without restarting.
- The per-user views folder is created automatically on first launch.

### Changed

- Distribution is now a single self-contained executable (PyInstaller one-file
  build) instead of an executable plus a companion folder.
- Cleaned up the PyInstaller spec: removed stale hidden imports and corrected
  the bundled `ampm` module list.

## [1.0.0] - 2026-06-03

Initial release.

### Added

- Desktop GUI (PyQt6) with a Config tab (build selection, paths, parameters)
  and an Analysis tab (derived columns, plot view/axes/settings).
- End-to-end pipeline: per-layer Parquet cache, STL-based masking, part
  assignment (direct nearest-part or DBSCAN clustering), and per-part
  coefficient-of-variation statistics. Each stage is cached under
  `<source>/.cache/`.
- Pluggable, auto-discovered plot views (scatter 2D/3D, contour, KDE, bar,
  layer and single-layer viewers, CoV summary, k-distance).
- Layer range selection. Load a *From* / *To* subset instead of the whole
  build, bounded to the range detected in the source.
- Chunked direct part assignment with bounded memory for full builds (tens of
  millions of rows).
- Per-range cache files so switching between layer ranges reuses earlier work;
  parameter changes recompute only what's affected instead of erroring.
- Per-build session memory: pipeline parameters, derived-column recipes, and
  the selected plot view/axes/settings are saved beside each build in
  `.ampm-ui.json` and restored on reopen. `config.toml` is never modified.
- Last project-root folder remembered between launches.
- Progress feedback: phase-by-phase load progress and a plotting busy
  indicator.
- Input validation before loading, with **Load Data** disabled until required
  inputs are present.
- Collapsible data-source paths; **Plot** button positioned at the bottom of
  the Analysis tab.
- Dropdowns ignore the mouse wheel (scrolls the page instead of changing the
  selection).
- CLI launcher with startup retry and graceful `Ctrl+C` handling (second
  `Ctrl+C` forces quit).
- Documentation: GUI user guide (`docs/APP.md`), README, and pipeline docs.

[Unreleased]: https://github.com/Obbaron/ampm-analysis/compare/v1.1.2...HEAD
[1.1.2]: https://github.com/Obbaron/ampm-analysis/compare/v1.1.1...v1.1.2
[1.1.1]: https://github.com/Obbaron/ampm-analysis/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/Obbaron/ampm-analysis/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/Obbaron/ampm-analysis/releases/tag/v1.0.0