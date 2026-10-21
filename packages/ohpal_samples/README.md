# ohpal-samples

Turns hand-written characterisation workbooks (density, EDX, roughness,
microhardness, …) into tidy polars frames for analysis and, later, for
contributing columns to the cross-package part matrix.

## Tier 1 — standalone analysis (here)

No build file, no `part_id` required.

```python
from ohpal.samples import read_table, summarize_readings

df = read_table("Archimedes_Density_TiAg.xlsx", sheet="Ti-Sterling")
df = summarize_readings(df, prefix="Density")   # -> density_avg / density_sd / density_n
```

**`read_table`** copes with real workbooks: it keeps the contiguous titled
column block (severing aside/pivot tables parked behind two blank headers),
takes the rows where the anchor column (`Cube ID` by default) is populated,
turns blank cells into nulls without shifting rows, and keeps id-like columns as
text so `1+` / `007` / `name#2` survive. Reads `.xlsx`/`.xlsm`/`.xls` and
`.csv`/`.tsv`.

**`summarize_readings`** detects the replicate columns (`Density (1)..(6)`,
`Density 1..3`, … — count and spelling vary per sheet) and adds a null-safe
average, sample SD, and count. It recomputes from the raw readings and never
trusts the human's in-sheet `AVG`/`σ`.

## Tier 2 — part-attribute provider (next)

Adds `part_id` via `ohpal.core`'s identity chain and namespaces columns so
`merge()` can fold them into the part matrix. Will add `ohpal-core` as a
dependency. Not built yet.

## Dev

```bash
uv run --package ohpal-samples pytest packages/ohpal_samples/tests -q
```
