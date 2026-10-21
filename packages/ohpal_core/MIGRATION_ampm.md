# Repointing `ohpal.ampm` at `ohpal.core.build`

This is the second half of the first PR. `ohpal.core.build` now owns the
build-file reader and the part-identity primitive; `ohpal.ampm.parts` keeps its
QuantAM reader and its bulk/cluster spatial functions and just imports the
reader from core. The change is **non-breaking**: a thin back-compat adapter
gives the existing spatial functions the exact column spelling they already use.

## 1. Delete from `packages/ohpal_ampm/src/ohpal/ampm/parts.py`

Remove these four blocks (they now live in `ohpal.core.build`):

| Symbol | Lines (in the version you sent) |
|---|---|
| `_DHXML_PARTS_PATH = (...)` | 395 |
| `_parse_bounding_box(...)` | 398–414 |
| `_suffix_duplicate_names(...)` | 417–432 |
| `class BuildStartedDHXML` | 435–538 |

Also drop `import json` (line 46) — it was only used by the reader you just
removed. **Keep** `from collections import Counter`: `compute_part_id_map`
(line 634) still uses it.

## 2. Add the import + back-compat adapter

Near the top of `parts.py`, after the existing imports:

```python
from ohpal.core.build import BuildParts


class BuildStartedDHXML(BuildParts):
    """Back-compat adapter: core :class:`BuildParts` with QuantAM column names.

    ``ohpal.core`` exposes neutral, canonical columns (``part_id``, ``x_min`` …).
    The ampm spatial functions (``assign_bounding_box_part``,
    ``compute_part_id_map`` …) were written against QuantAM's spelling
    (``Part ID``, ``X min`` …, ``X Position``/``Y Position``), so this adapter
    renames the core table back to that vocabulary. New ampm code should prefer
    ``BuildParts`` + canonical names directly.
    """

    _QUANTAM = {
        "part_id": "Part ID",
        "x_min": "X min", "y_min": "Y min", "z_min": "Z min",
        "x_max": "X max", "y_max": "Y max", "z_max": "Z max",
        "x_center": "X Position", "y_center": "Y Position",
    }

    def parts_table(self):  # type: ignore[override]
        return super().parts_table().drop("name").rename(self._QUANTAM)
```

Because `BuildParts.from_dhxml`/`from_path` construct via `cls(...)`,
`BuildStartedDHXML.from_path(...)` returns a `BuildStartedDHXML`, so the
override applies. Every existing call site keeps working with no signature
changes — verified: the adapter yields
`['Part ID', 'X min', 'Y min', 'Z min', 'X max', 'Y max', 'Z max', 'X Position', 'Y Position']`,
covering the defaults of both `assign_bounding_box_part` and
`compute_part_id_map`.

## 3. Declare the workspace dependency

In `packages/ohpal_ampm/pyproject.toml`:

```toml
[project]
dependencies = [
    "ohpal-core",
    # … existing deps …
]

[tool.uv.sources]
ohpal-core = { workspace = true }
```

Then from the repo root: `uv sync --all-packages`.

## Deferred (not in this PR)

* `assign_bounding_box_part` still carries its own inside-test loop. It can
  later call the core `BuildParts._containing` primitive, but that is an
  internal refactor with no behaviour change and isn't required for correctness.
* `join_parts_with_stats` is a special case of the future `ohpal.core` merge /
  orchestrator; fold it in when that lands rather than maintaining two joins.
* `compute_part_id_map` / `apply_part_id_map` are the heavy `AmpmClusterResolver`
  path; they stay in ampm and get wired into the identity chain later.
