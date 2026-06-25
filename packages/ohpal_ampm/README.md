# ohpal.ampm

Analysis pipeline for **Renishaw 500S PBF-LB AMPM** (additive-manufacturing process
monitoring) data. It takes melt-pool monitoring packets from the machine and turns them
into a per-point enriched dataset and per-part statistics ready for plotting.

- **Distribution:** `ohpal-ampm`
- **Import as:** `ohpal.ampm`

```python
from ohpal.ampm import DataStore, load_config, create_or_load_config
```

## What it does

The pipeline runs as a sequence of stages, each backed by a module:

| # | Stage | Module | Role |
| --- | ------- | -------- | ------ |
| 1 | Config | `config` | resolve run parameters and ranges (`create_or_load_config`) |
| 2 | Load | `datastore` | read packet files into a Polars frame (`DataStore`) |
| 3 | Mask | `masking` | keep points inside the part geometry (`build_mask`, `apply_mask_keep`, `stl_hash`) |
| 4 | Assign parts | `parts` | tag each point with its `part_id` and per-part metadata (`BuildStartedDHXML`, `QuantAMParts`) |
| 5 | Cluster | `clustering` | DBSCAN over XY/Z, chunked by layer (`cluster_dbscan_chunked`) |
| 6 | Correct | `correction` | apply melt-pool calibration (`MeltPoolCorrection`) |
| 7 | Stats | `stats` | per-part metrics, e.g. coefficient of variation (`compute_cov`, `CovMode`) |

The two expensive stages are cached: `mask_cache.mask_or_load` and
`cluster_cache.cluster_or_load` memoise results keyed on the inputs (the mask cache uses
`stl_hash` of the geometry), so re-runs with unchanged inputs skip recomputation.

Supporting modules: `sampling` (downsampling), `plotting` (figure construction), and
`setup_build` (build scaffolding).

### Inputs

- **Packet data**: `.txt` files, per layer / per laser.
- **STL geometry**: the part meshes used for masking.
- **Parts CSV**: QuantAM parts table.
- **QuantAM build file (DHXML)**: used for part assignment on merged builds (no .amx).

### Output

- An **enriched frame** carrying, per point: `part_id`, cluster label, and corrected signal.
- **Per-part statistics** (e.g. CoV by part) ready to hand to a plotting view.

## Public API

The package re-exports the most-used entry points at the top level:

```python
from ohpal.ampm import (
    DataStore,            # load / hold monitoring data
    load_config,          # load an existing run config
    create_or_load_config # create one if missing, else load
)
```

Stage-specific functions live in their modules and can be imported directly, e.g.:

```python
from ohpal.ampm.masking import build_mask, apply_mask_keep, stl_hash
from ohpal.ampm.parts import QuantAMParts, BuildStartedDHXML
from ohpal.ampm.clustering import cluster_dbscan_chunked
from ohpal.ampm.correction import MeltPoolCorrection
from ohpal.ampm.stats import compute_cov, CovMode
```

See the module docstrings and source for full signatures.

## Installation & development

This package is a member of the [OHPAL](../../README.md) (OHP Analytics Library) uv
workspace; the normal path is
to sync the whole workspace from the repo root:

```bash
uv sync --all-packages        # installs ohpal-ampm (editable) + its dev tools
```

To work with it outside the workspace, it installs like any standard package:

```bash
pip install -e packages/ohpal_ampm
```

### Tests

```bash
# at ohpal root:
just test
# equivalently from this directory:
uv run python -m pytest
```

## Dependencies

Core: `polars`, `pyarrow`, `numpy`, `scipy`, `scikit-learn`, `networkx`. Geometry:
`trimesh`, `shapely`, `rtree`. Plotting: `plotly`, `matplotlib`. (GUI concerns such as
PyQt6 belong to the [`ampm_analyzer`](../../apps/ampm_analyzer/README.md) app, not here —
this package is the headless pipeline.)

## A note on the namespace

`ohpal.ampm` is part of the PEP 420 `ohpal` namespace package. This package therefore
ships `src/ohpal/ampm/__init__.py` but **no** `src/ohpal/__init__.py`. the `ohpal/` level
stays empty of one so other distributions can share the namespace.

## License

All rights reserved.
