"""DBSCAN part assignment, run as a separate process.

Clustering a full build can take a long time, and a running scikit-learn
DBSCAN cannot be interrupted from Python. Running it as its own process lets
the app stop it at once (Cancel, or closing the app) and returns all of its
memory to the system when it ends.

The app's worker thread reads the points from the DataStore, writes them to a
parquet file, writes a small job file (JSON) describing the work, and starts
this module on it:

- from source:        ``python -m ampm_analyzer.dbscan_job <job.json>``
- in the packaged app: ``AMPM-Analyzer.exe --dbscan-job <job.json>``
  (``ampm_analyzer.__main__`` hands the flag here before any Qt loads)

The job file names ``input`` (the points), ``output`` (where the labels go),
``progress`` (a file this process appends one JSON line per message to),
``parts_csv`` and the clustering ``params``. Messages:

- ``["stage", text]``  what it is doing
- ``["chunk", i, n]``   clustering chunk ``i`` of ``n``
- ``["done", info]``    the labels are written
- ``["error", text]``   it could not finish (a one-line reason)

A file rather than stdout: the packaged app is a windowed program with no
console. No Qt here: this needs only Polars, scikit-learn and ``ohpal``.
"""

from __future__ import annotations

import json
import sys

FLAG = "--dbscan-job"   # the packaged app's command-line switch


def command(job_path: str) -> list[str]:
    """The command line that runs a job file."""
    if getattr(sys, "frozen", False):
        return [sys.executable, FLAG, job_path]
    return [sys.executable, "-m", "ampm_analyzer.dbscan_job", job_path]


def run(job: dict) -> None:
    """Cluster ``job["input"]`` and write one ``part_id`` per labelled point
    (``layer``, ``Start time``, ``part_id``) to ``job["output"]``."""
    with open(job["progress"], "a", encoding="utf-8") as out:
        def say(*msg) -> None:
            out.write(json.dumps(list(msg)) + "\n")
            out.flush()

        try:
            import polars as pl
            from ohpal.ampm.clustering import cluster_dbscan_chunked
            from ohpal.ampm.parts import (
                QuantAMParts, apply_part_id_map, compute_part_id_map)

            params = job["params"]
            # glob=False: build folders are often named like "[3] Export
            # Packets", which Polars would read as a wildcard.
            df = pl.read_parquet(job["input"], glob=False)
            say("stage", "clustering")
            clustered = cluster_dbscan_chunked(
                df,
                eps_xy=params["eps_xy"], eps_z=params["eps_z"],
                min_samples=params["min_samples"], mode="3d",
                layers_per_chunk=params["layers_per_chunk"],
                overlap_layers=params["overlap_layers"],
                layer_thickness=params["layer_thickness"], verbose=False,
                progress=lambda i, n: say("chunk", i, n),
            )
            del df
            say("stage", "matching clusters to parts")
            parts = QuantAMParts.from_path(job["parts_csv"]).parent_parts()
            mapping = compute_part_id_map(clustered, parts, verbose=False)
            labels = (
                apply_part_id_map(clustered, mapping)
                .filter(pl.col("part_id").is_not_null())
                .select(["layer", "Start time", "part_id"])
                .unique(subset=["layer", "Start time"], keep="first",
                        maintain_order=True)
            )
            if labels.is_empty():
                say("error",
                    "DBSCAN found no cluster that matches a part of the parts "
                    "CSV. Try other settings (the XY and Z radius, min "
                    "samples) on the DataStore setup page; the K-distance "
                    "curve plot helps choose them.")
                return
            labels.write_parquet(job["output"])
            say("done", {"n_parts": labels["part_id"].n_unique(),
                         "n_labelled": labels.height})
        except MemoryError:
            say("error",
                "Ran out of memory while clustering. Try fewer layers per "
                "chunk (config.toml, [clustering] layers_per_chunk) or a "
                "smaller layer range.")
        except SystemExit as exc:  # ohpal helpers can call sys.exit()
            say("error", f"Aborted: {exc}")
        except Exception as exc:  # noqa: BLE001 - a clear one-line reason
            say("error", f"{type(exc).__name__}: {exc}")


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m ampm_analyzer.dbscan_job <job.json>",
              file=sys.stderr)
        return 2
    with open(argv[0], encoding="utf-8") as fh:
        run(json.load(fh))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
