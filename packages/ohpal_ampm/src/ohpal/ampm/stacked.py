"""
stacked.py - several builds stacked into one ("stepped" builds)

A stepped build is printed as separate jobs, each on top of the last. Each step
is an ordinary build folder (its own packet data, STL, parts CSV / .dhxml and
DataStore cache); a **stacked build** reads them together as if they were one
continuous build:

- ``layer`` continues from step to step: a step's first layer follows the
  previous step's last (its own numbering restarts at 1);
- ``Z`` continues the same way (each step's layers at its own thickness);
- ``step`` (1, 2, ...) says which step a row came from;
- ``Build time`` (seconds) runs on through every layer and step: each layer
  starts where the previous one ended (the packet data's ``Start time``
  restarts at every layer, and the time between layers isn't recorded);
- ``part_id`` takes the step as a prefix (``S2 Part(3)``): a part never spans
  steps, and steps reuse part names.

A stacked build lives in its own folder, as ``stacked.toml`` (its name and the
steps' folders, in order); the folder also holds its own ``.cache`` for app
state. The steps' Parquet caches are their own (shared with opening a step on
its own).

Usage
-----
    from ohpal.ampm.stacked import write_stack, load_stack

    write_stack("D:/builds/JR300 stacked", "JR300", ["D:/builds/JR300 s1",
                                                     "D:/builds/JR300 s2"])
    store = load_stack("D:/builds/JR300 stacked")
    df = store.query(layers=(195, 205), columns=["MeltVIEW melt pool (mean)"])
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import polars as pl

from ohpal.ampm.datastore import DataStore

STACK_FILE = "stacked.toml"
STEP = "step"
BUILD_TIME = "Build time"
VIRTUAL = (STEP, BUILD_TIME)
_TIMES_FILE = "layer_times.json"


def is_stack(folder) -> bool:
    """True if ``folder`` is a stacked build (holds ``stacked.toml``)."""
    return (Path(folder) / STACK_FILE).is_file()


def write_stack(folder, name: str, steps: Iterable) -> Path:
    """Write ``stacked.toml`` into ``folder`` (created if needed): the stack's
    name and its steps' build folders, bottom first. Step paths are stored
    relative to ``folder`` when they share a drive, so the set can move
    together."""
    import os

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    lines = ["# A stacked (stepped) build: these builds, bottom first, read as",
             "# one continuous build. Paths are relative to this file's folder.",
             "", f"name = {json.dumps(str(name))}", "", "steps = ["]
    for step in steps:
        p = Path(step).resolve()
        try:
            shown = os.path.relpath(p, folder.resolve())
        except ValueError:  # another drive
            shown = str(p)
        lines.append(f"    {json.dumps(shown.replace(chr(92), '/'))},")
    lines += ["]", ""]
    path = folder / STACK_FILE
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def read_stack(folder) -> tuple[str, list[Path]]:
    """The stack's name and its steps' folders (absolute), bottom first."""
    try:
        import tomllib
    except ModuleNotFoundError:  # Python < 3.11
        import tomli as tomllib

    folder = Path(folder)
    with open(folder / STACK_FILE, "rb") as fh:
        data = tomllib.load(fh)
    steps = [(folder / s).resolve() for s in data.get("steps") or []]
    if len(steps) < 2:
        raise ValueError(f"{folder / STACK_FILE} needs at least two steps.")
    for s in steps:
        if not s.is_dir():
            raise FileNotFoundError(f"Step folder not found: {s}")
    return str(data.get("name") or folder.name), steps


@dataclass
class StackStep:
    """One step of a stacked build."""
    index: int                 # 1, 2, ...
    root: Path                 # the step's build folder
    store: DataStore
    config: dict = field(default_factory=dict)
    layer_offset: int = 0      # stacked layer = the step's own layer + this
    z_base: float = 0.0        # the stack's height below this step (mm)

    @property
    def label(self) -> str:
        return f"S{self.index}"

    @property
    def first(self) -> int:
        return self.store.layers[0]

    @property
    def last(self) -> int:
        return self.store.layers[-1]

    @property
    def thickness(self) -> float:
        return float(self.store.layer_thickness)

    def stacked(self, local: int) -> int:
        return int(local) + self.layer_offset

    def local(self, stacked: int) -> int:
        return int(stacked) - self.layer_offset


def load_stack(folder, *, create_configs: bool = False) -> "StackedStore":
    """Open a stacked build: each step's config and DataStore, stacked."""
    from ohpal.ampm.config import load_config

    folder = Path(folder)
    name, roots = read_stack(folder)
    steps = []
    for root in roots:
        if create_configs and not (root / "config.toml").exists():
            from ohpal.ampm.setup_build import create_config

            create_config(root)
        config = load_config(root)
        thickness = float(config.get("LAYER_THICKNESS") or 0.03) or 0.03
        store = DataStore(Path(config["SOURCE"]), layer_thickness=thickness)
        steps.append((root, store, config))
    return StackedStore(steps, cache_dir=folder / ".cache", name=name)


class StackedStore:
    """Several DataStores read as one continuous build (see the module notes).

    Offers the parts of the ``DataStore`` interface the app uses: ``layers``,
    ``columns``, ``query``, ``build_cache``, ``cached_layers``,
    ``set_part_assignment`` and ``cache_dir`` (the stack's own, for app
    state).
    """

    def __init__(self, steps, *, cache_dir, name: str = "stacked") -> None:
        self.name = name
        self.cache_dir = Path(cache_dir)
        self.steps: list[StackStep] = []
        offset, z = None, 0.0
        for i, (root, store, config) in enumerate(steps, start=1):
            step = StackStep(i, Path(root), store, dict(config or {}))
            if offset is None:  # the bottom step keeps its own numbering
                offset = step.first - 1
                z = offset * step.thickness
            # Its first layer follows the previous step's last.
            step.layer_offset = offset - step.first + 1
            step.z_base = z
            self.steps.append(step)
            offset = step.stacked(step.last)
            z += (step.last - step.first + 1) * step.thickness
        self._layer_step: dict[int, StackStep] = {}
        for step in self.steps:
            for L in step.store.layers:
                self._layer_step[step.stacked(L)] = step
        self._times: dict | None = None   # (root, layer) -> layer end, us

    # -- the DataStore interface -------------------------------------------
    @property
    def layers(self) -> list[int]:
        return sorted(self._layer_step)

    @property
    def layer_thickness(self) -> float:
        return self.steps[0].thickness

    @property
    def source_dir(self) -> Path:
        return self.cache_dir.parent

    @property
    def columns(self) -> list[str]:
        """The columns every step has (``part_id`` when every step has an
        assignment), plus ``step`` and ``Build time``."""
        first = self.steps[0].store.columns
        common = [c for c in first
                  if all(c in s.store.columns for s in self.steps[1:])]
        return [*common, *VIRTUAL]

    def step_of(self, layer: int) -> StackStep:
        return self._layer_step[int(layer)]

    def cached_layers(self) -> set[int]:
        """The stacked layers whose Parquet is in their step's cache."""
        out = set()
        for step in self.steps:
            out |= {step.stacked(L) for L in step.store.cached_layers()}
        return out

    def build_cache(self, layers: Iterable[int] | None = None, force: bool = False,
                    verbose: bool = True) -> None:
        for step, local in self._split(layers):
            step.store.build_cache(layers=local, force=force, verbose=verbose)

    def set_part_assignment(self, parts_table, *, method: str = "bbox",
                            max_distance_mm=None) -> None:
        """The same assignment for every step (``None`` clears them). Steps
        have their own parts: use ``set_step_part_assignment`` for those."""
        for step in self.steps:
            step.store.set_part_assignment(
                parts_table, method=method, max_distance_mm=max_distance_mm)

    def set_step_part_assignment(self, index: int, parts_table, *,
                                 method: str = "bbox",
                                 max_distance_mm=None) -> None:
        self.steps[index - 1].store.set_part_assignment(
            parts_table, method=method, max_distance_mm=max_distance_mm)

    def query(self, layers=None, columns: list[str] | None = None,
              sample_to: int | None = None, **filters) -> pl.DataFrame:
        """Rows of the stacked ``layers`` (a ``(lo, hi)`` range, an iterable or
        None for all), with ``layer`` / ``Z`` continued, ``step``, ``Build
        time`` and step-prefixed ``part_id``. ``sample_to`` is shared across
        the steps by how many of the layers each holds."""
        parts = self._split(layers)
        if not parts:
            raise ValueError("No layers selected by the given 'layers' argument.")
        want_time = columns is None or BUILD_TIME in columns
        want_step = columns is None or STEP in columns
        own = None
        if columns is not None:
            own = [c for c in columns if c not in VIRTUAL]
            if want_time and "Start time" not in own:
                own.append("Start time")
        total = sum(len(local) for _, local in parts)
        frames = []
        for step, local in parts:
            share = (None if sample_to is None else
                     max(1, -(-int(sample_to) * len(local) // total)))
            df = step.store.query(layers=local, columns=own, sample_to=share,
                                  **filters)
            frames.append(self._continue(step, df, want_step, want_time))
        out = pl.concat(frames, how="diagonal_relaxed")
        if columns is not None:
            keep = list(dict.fromkeys([*columns, "layer", "Z"]))
            out = out.select([c for c in keep if c in out.columns])
        return out

    # -- how the steps join up -----------------------------------------
    def _split(self, layers) -> list[tuple[StackStep, list[int]]]:
        """Stacked layers -> (step, its own layers) pairs, bottom first."""
        if layers is None:
            wanted = set(self._layer_step)
        elif isinstance(layers, tuple) and len(layers) == 2:
            lo, hi = int(layers[0]), int(layers[1])
            wanted = {L for L in self._layer_step if lo <= L <= hi}
        else:
            wanted = {int(L) for L in layers} & set(self._layer_step)
        out = []
        for step in self.steps:
            local = sorted(step.local(L) for L in wanted
                           if self._layer_step[L] is step)
            if local:
                out.append((step, local))
        return out

    def _continue(self, step: StackStep, df: pl.DataFrame, want_step: bool,
                  want_time: bool) -> pl.DataFrame:
        cols = [
            (pl.col("layer").cast(pl.Int64) + step.layer_offset)
            .cast(pl.Int32).alias("layer"),
            # Z from the step's own layer at its thickness, on top of the
            # steps below.
            (pl.lit(step.z_base) + (pl.col("layer").cast(pl.Float64)
                                    - step.first + 1) * step.thickness)
            .cast(pl.Float32).alias("Z"),
        ]
        if want_step:
            cols.append(pl.lit(step.index, dtype=pl.Int8).alias(STEP))
        if want_time and "Start time" in df.columns:
            starts = self._layer_starts()
            lut = pl.DataFrame(
                {"layer": [L for L in step.store.layers],
                 "_t0": [starts[(str(step.root), L)] for L in step.store.layers]},
                schema={"layer": df.schema["layer"], "_t0": pl.Int64})
            df = df.join(lut, on="layer", how="left", maintain_order="left")
            cols.append(((pl.col("_t0") + pl.col("Start time").cast(pl.Int64))
                         / 1e6).alias(BUILD_TIME))
        if "part_id" in df.columns:
            cols.append(pl.when(pl.col("part_id").is_not_null())
                        .then(pl.lit(step.label + " ")
                              + pl.col("part_id").cast(pl.Utf8))
                        .otherwise(None).alias("part_id"))
        out = df.with_columns(cols)
        return out.drop("_t0") if "_t0" in out.columns else out

    # -- Build time -----------------------------------------------------
    def _layer_end(self, step: StackStep, layer: int) -> int | None:
        """When a layer's last packet ends (us from the layer's start), from
        its Parquet; None if it isn't in the cache yet."""
        path = step.store._cache_path(layer)
        if not path.exists():
            return None
        try:
            # glob=False: build folders are often named like "[3] Export
            # Packets", which Polars would read as a wildcard.
            row = (pl.scan_parquet(str(path), glob=False)
                   .select((pl.col("Start time").cast(pl.Int64)
                            + pl.col("Duration").cast(pl.Int64)).max())
                   .collect())
            value = row.item()
            return int(value) if value is not None else 0
        except Exception:  # noqa: BLE001 - a damaged file: treat as unknown
            return None

    def _layer_starts(self) -> dict[tuple[str, int], int]:
        """Each layer's start on the build clock (us): the sum of the layers
        below. Layer ends are kept in the stack's cache, keyed by their
        Parquet's modification time; one not built yet counts as the median
        of the known ones."""
        if self._times is not None:
            return self._times
        saved_path = self.cache_dir / _TIMES_FILE
        try:
            saved = json.loads(saved_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        ends: dict[tuple[str, int], int | None] = {}
        fresh = {}
        for step in self.steps:
            for L in step.store.layers:
                path = step.store._cache_path(L)
                key = f"{step.root}|{L}"
                try:
                    stamp = path.stat().st_mtime_ns
                except OSError:
                    stamp = None
                hit = saved.get(key)
                if stamp is not None and hit and hit[0] == stamp:
                    end = hit[1]
                else:
                    end = self._layer_end(step, L)
                if stamp is not None and end is not None:
                    fresh[key] = [stamp, end]
                ends[(str(step.root), L)] = end
        known = sorted(v for v in ends.values() if v is not None)
        fill = known[len(known) // 2] if known else 0
        starts, clock = {}, 0
        for step in self.steps:
            for L in step.store.layers:
                starts[(str(step.root), L)] = clock
                end = ends[(str(step.root), L)]
                clock += end if end is not None else fill
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            saved_path.write_text(json.dumps(fresh), encoding="utf-8")
        except OSError:
            pass
        # Only kept when every layer was known (else look again next time).
        if len(known) == len(ends):
            self._times = starts
        return starts

    def forget_times(self) -> None:
        """Re-read the layer times (after a step's cache was rebuilt)."""
        self._times = None

    # -- masks ------------------------------------------------------------
    def stacked_mask(self, step: StackStep, mask: dict) -> dict:
        """A step's layer mask (its own layer -> polygon) keyed by stacked
        layer."""
        return {step.stacked(L): poly for L, poly in (mask or {}).items()}
