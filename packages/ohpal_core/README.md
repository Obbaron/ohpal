# ohpal-core

The lowest package in the `ohpal` workspace. It owns shared contracts and the
build-file identity primitives, so `ohpal.samples` and `ohpal.ampm` can both
depend on it without depending on each other (a diamond, not a cycle).

## What's here so far

`ohpal.core.build`
- **`BuildParts`** — reads a Renishaw *BuildStarted* `.dhxml` (JSON despite the
  extension) into per-part names + 3D bounding boxes. Mints the canonical join
  key `part_id` (`Utf8`), suffixing repeated names `name#n`.
- **`BuildParts.parts_table()`** — one row per part, canonical neutral column
  names (`part_id`, `name`, `{x,y,z}_{min,max}`, `x_center`, `y_center`).
- **`BuildParts.part_at(x, y, ...)` / `.part_ids_at(df, ...)`** — the strict
  point-in-bounding-box resolver. Exactly one containing box → that `part_id`;
  zero or many → `PartResolutionError` (never guesses). Optional `tol` allows a
  unique nearest box within a small margin, for rounding at the edges.

Dependencies are intentionally light (numpy + polars). The KDTree-backed *bulk*
point-cloud assignment stays in `ohpal.ampm`.

## Roadmap (designed, not yet built)

- `ohpal.core.identity` — `PartIdentityResolver` protocol + resolution chain
  (direct column → spatial bbox → ampm-cluster stub).
- `ohpal.core.parts` — the `PartAttributeProvider` contract, `merge()`
  orchestrator, and the canonical `(build_id, part_id)` key handling.

## Dev

```bash
uv sync --all-packages
uv run --package ohpal-core pytest packages/ohpal_core/tests -q
```
