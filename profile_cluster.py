"""
Scalene profiling driver for the ampm pipeline.

Runs a representative end-to-end workload (query -> mask -> cluster) so the
profiler can surface the real hotspots. This is NOT a test: it exercises the
library the way a production analysis run does, on real data.

Usage (Windows, venv active):
    scalene run profile_pipeline.py
    scalene view                          # reopen the last profile in a browser

Handy flags:
    scalene run --profile-only ampm profile_pipeline.py   # only your package
    scalene run --reduced-profile profile_pipeline.py      # only hot lines
    scalene run --cpu --memory profile_pipeline.py         # choose channels

Profile with coverage OFF: pytest-cov's line tracing badly distorts both
timings and allocation counts.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path

import polars as pl

from ampm.clustering import cluster_dbscan_chunked, cluster_summary
from ampm.datastore import DataStore
from ampm.masking import apply_mask, build_mask

SOURCE_DIR = Path(
    r"C:\Users\ohp460\Documents\Code\ampm-analysis\data\JR327_02062026\[3] Export Packets"
)
STL_PATH = Path(
    r"C:\Users\ohp460\Documents\Code\ampm-analysis\data\JR327_02062026\Layout_1.stl"
)
LAYER_LO, LAYER_HI = 101, 300

LAYER_THICKNESS = 0.03
EPS_XY, EPS_Z, MIN_SAMPLES = 0.3, 0.06, 10  # DBSCAN parameters

CACHE_DIR = None  # None = DataStore manages its own cache; or set a path
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
        store = DataStore(
            SOURCE_DIR, layer_thickness=LAYER_THICKNESS, cache_dir=CACHE_DIR
        )
        df = store.query(layers=(LAYER_LO, LAYER_HI))
    print(f"  queried {df.height:,} rows x {df.width} cols")
    if df.is_empty():
        print("  empty query — check SOURCE_DIR / layer range; nothing to profile.")
        return

    with stage("build_mask"):
        mask = build_mask(
            STL_PATH,
            layers=layers,
            layer_thickness=LAYER_THICKNESS,
            cache_path=MASK_CACHE,
        )
    print(f"  mask covers {len(mask):,} layers")

    with stage("apply_mask"):
        df = apply_mask(df, mask)
    print(f"  {df.height:,} rows survive the mask")
    if df.is_empty():
        print("  nothing inside the mask; stopping before clustering.")
        return

    with stage("cluster_dbscan_chunked"):
        clustered = cluster_dbscan_chunked(
            df,
            eps_xy=EPS_XY,
            eps_z=EPS_Z,
            min_samples=MIN_SAMPLES,
            mode="3d",
            layer_thickness=LAYER_THICKNESS,
            verbose=False,
        )
    n_clusters = clustered.filter(pl.col("cluster") >= 0)["cluster"].n_unique()
    print(f"  found {n_clusters:,} clusters")

    with stage("cluster_summary"):
        summary = cluster_summary(clustered)
    print(f"  summary: {summary.height:,} rows")


if __name__ == "__main__":
    main()
