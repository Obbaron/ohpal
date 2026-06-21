"""
Scalene profiling driver for the DIRECT part-assignment path.

Mirrors the GUI's `METHOD == "direct"` branch (app.py): load -> mask ->
assign_nearest_part. The focus is the assignment stage; masking runs first so
the assignment sees a realistic, masked frame exactly as it does in the app.

Usage (Windows, venv active, in your project directory):
    scalene run --profile-only ampm profile_direct.py
    scalene view                          # reopen the last profile

Profile with coverage OFF; pytest-cov's line tracing distorts the numbers.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path

import polars as pl

from ampm.datastore import DataStore
from ampm.masking import apply_mask, build_mask
from ampm.parts import QuantAMParts, assign_nearest_part

SOURCE = Path(
    r"C:\Users\ohp460\Documents\Code\ampm-analysis\data\JR327_02062026\[3] Export Packets"
)
STL = Path(
    r"C:\Users\ohp460\Documents\Code\ampm-analysis\data\JR327_02062026\Layout_1.stl"
)
PARTS_CSV = Path(
    r"C:\Users\ohp460\Documents\Code\ampm-analysis\data\JR327_02062026\Untitled.csv"
)
LAYER_LO, LAYER_HI = 101, 300

LAYER_THICKNESS = 0.03
MAX_DISTANCE_MM = None

APPLY_MASK = True
MASK_CACHE = None


@contextmanager
def stage(name: str):
    """Print wall-clock time per stage so the profile is easy to map back."""
    print(f"[stage] {name} ...", flush=True)
    t0 = time.perf_counter()
    yield
    print(f"[stage] {name}: {time.perf_counter() - t0:.2f}s", flush=True)


def main() -> None:
    layers = range(LAYER_LO, LAYER_HI + 1)

    with stage("DataStore.query"):
        store = DataStore(SOURCE, layer_thickness=LAYER_THICKNESS)
        df = store.query(layers=(LAYER_LO, LAYER_HI))
    print(f"  queried {df.height:,} rows x {df.width} cols")
    if df.is_empty():
        print("  empty query — check SOURCE / layer range; nothing to profile.")
        return

    if APPLY_MASK:
        with stage("build_mask"):
            mask = build_mask(
                STL,
                layers=layers,
                layer_thickness=LAYER_THICKNESS,
                buffer_mm=0.0,
                cache_path=MASK_CACHE,
            )
        with stage("apply_mask"):
            df = apply_mask(df, mask)
        print(f"  {df.height:,} rows survive the mask")
        if df.is_empty():
            print("  nothing inside the mask; stopping before assignment.")
            return

    with stage("QuantAMParts.parent_parts"):
        quantam = QuantAMParts.from_path(PARTS_CSV)
        parts_table = quantam.parent_parts()
    print(f"  loaded {parts_table.height} parts")

    # The stage we actually care about: direct nearest-part assignment.
    with stage("assign_nearest_part  (DIRECT)"):
        df = assign_nearest_part(
            df,
            parts_table,
            max_distance_mm=MAX_DISTANCE_MM,
            noise_label="noise",
        )

    try:
        assigned = df.filter(pl.col("part_id") != "noise").height
        print(f"  assigned {assigned:,}/{df.height:,} rows to a part")
    except Exception:
        print(f"  done: {df.height:,} rows now carry a part_id")


if __name__ == "__main__":
    main()
