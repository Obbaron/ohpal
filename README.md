# OHP Analysis Library

**OHPAL** is a monorepo for a set of analysis libraries
published under the shared `ohpal` namespace, plus the applications and plugins built on
top of them.
Its first focus is **PBF-LB additive-manufacturing post-process monitoring**; plotting packet data and columnar statistics from Renishaw 500S AMPM system.

## Repository layout

```
ohpal/
├── apps/
│   └── ampm_analyzer/        # PyQt6 GUI for exploring AMPM data
├── packages/                 # libraries under the `ohpal.*` namespace
│   ├── ohpal_ampm/           # AMPM analysis pipeline
│   └── ohpal_micrographs/    # Microscopy image analysis
├── plugins/                  # optional plugins under ohpal.plugins.*
├── docs/
├── scripts/
├── justfile                  # task runner (see "Tasks" below)
├── pyproject.toml            # uv workspace root (no [project])
└── uv.lock
```

This is a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/): every
package and app is a member, they depend on each other locally via
`[tool.uv.sources] … = { workspace = true }` and share one `.venv`.

### The `ohpal` namespace

`ohpal` is a [PEP 420 native namespace package](https://peps.python.org/pep-0420/). It is
**not** owned by any single distribution. Rather each package contributes its own subtree
(`ohpal.ampm`, `ohpal.micrographs`, _etc._). The practical rule: there must be **no
`__init__.py` at the `ohpal/` level** in any package (nor `ohpal/plugins/`). Only the
leaf packages, _e.g._ `ohpal/ampm/__init__.py`, have one. A stray `ohpal/__init__.py`
collapses the namespace and breaks imports across packages. Use `just verify` to confirm namespaces resolve correctly.

## Requirements

- **Python 3.11, 64-bit**: distribution builds rely on the cp311 wheel ABI.
- **[uv](https://docs.astral.sh/uv/)** for dependency and environment management.
- **[just](https://just.systems/)** (optional) as the task runner — `uv tool install rust-just`.

## Quick start

```bash
# run at repo root
uv sync --all-packages        # create .venv and install every member (editable) + dev tools
uv run ampm-analyzer          # launch the GUI
```

Or with the task runner:

```bash
just setup     # uv sync --all-packages
just verify    # smoke-test the install and the ohpal namespace
just run       # launch the AMPM Analyzer GUI
```

## Tasks

Run `just` to list available tasks:

| Task | What it does |
| ------ | -------------- |
| `setup` | sync the venv and install all workspace members (editable) |
| `verify` | smoke-test Python version, imports, and the `ohpal` namespace |
| `run` | launch the AMPM Analyzer GUI |
| `test` | run the pipeline test suite |
| `build` | compile the standalone binary from `apps/ampm_analyzer/app.spec` |
| `clean` | remove caches and build artifacts |
| `rebuild` | clean, then build |

`run`, `test`, and `verify` use the environment as-is (they assume you've run `setup`);
`build` re-syncs first so binaries are never frozen against a stale environment. After
changing a dependency or pulling a commit that touches a `pyproject.toml` / `uv.lock`,
re-run `just setup` before trusting `test`/`run`.

## Working without uv

The packages are standard PEP 621 projects, so they remain pip-installable for anyone who
just wants to use or build them. For development without uv, the workspace wiring
(`[tool.uv.sources]`) isn't read by pip, so install the members editable by hand instead:

```bash
pip install -e packages/ohpal_ampm -e apps/ampm_analyzer
```

## Components

- [`packages/ohpal_ampm`](packages/ohpal_ampm/README.md): the AMPM analysis pipeline (`ohpal.ampm`)
- [`apps/ampm_analyzer`](apps/ampm_analyzer/README.md): the GUI application

## License

All rights reserved.
