"""Background workers.

QObject workers moved onto a QThread (the modern pattern — not QThread
subclassed with logic in run()). Each worker exposes the standard contract:
``progress(int, str)``, ``finished(object)``, ``error(str)``.

Rules followed here: the worker never touches widgets; all results leave via
signals (delivered on the main thread); exceptions — including the ``SystemExit``
that ohpal's config helpers can raise — become ``error`` signals rather than
killing anything.
"""

from __future__ import annotations

import time
import traceback
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from .state import QueryResult


class LoadWorker(QObject):
    """Loads (or creates) a build's config and constructs its DataStore, off the
    UI thread.

    This is where the first ``import ohpal`` happens — which cascades into
    ``polars`` / ``pyarrow`` and costs ~2s cold on the first build open. Running
    it here keeps the window responsive instead of freezing. Emits
    ``(config, store, source_dir, thickness, elapsed_ms)``; a ``create`` flag
    (decided on the main thread) says whether a missing config should be made.
    """

    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, build_root, *, create: bool) -> None:
        super().__init__()
        self._build_root = Path(build_root)
        self._create = create

    @pyqtSlot()
    def run(self) -> None:
        t = time.perf_counter()
        try:
            if self._create and not (self._build_root / "config.toml").exists():
                from ohpal.ampm.setup_build import create_config

                create_config(self._build_root)
            from ohpal.ampm.config import load_config

            config = load_config(self._build_root)
            source_dir = Path(config["SOURCE"])
            thickness = float(config.get("LAYER_THICKNESS") or 0.03) or 0.03
            from ohpal.ampm import DataStore

            store = DataStore(source_dir, layer_thickness=thickness)
        except SystemExit as exc:  # ohpal config helpers can call sys.exit()
            self.error.emit(f"Load aborted: {exc}")
        except Exception:  # noqa: BLE001 - surface any failure as a message
            self.error.emit(traceback.format_exc())
        else:
            self.finished.emit(
                (config, store, source_dir, thickness,
                 (time.perf_counter() - t) * 1000))


def find_build_inputs(build_root: Path) -> tuple[Path | None, Path | None]:
    """The build's ``BuildStarted`` .dhxml and QuantAM parts CSV, as
    ``(dhxml, parts_csv)`` — either may be None.

    A config.toml's ``[paths]`` wins when it names files that exist; otherwise
    the build folder itself is searched (a QuantAM export is recognised by its
    content, not its filename). Reads the toml directly, so a build with no
    DataStore — or an incomplete config — still works."""
    dhxml = quant = None
    cfg = build_root / "config.toml"
    if cfg.is_file():
        try:
            import tomllib

            paths = tomllib.loads(cfg.read_text(encoding="utf-8")).get("paths", {})
        except Exception:  # noqa: BLE001 — unreadable config: fall back to search
            paths = {}
        for key in ("dhxml", "parts_csv"):
            value = paths.get(key)
            if isinstance(value, str) and value.strip():
                p = Path(value)
                p = p if p.is_absolute() else build_root / p
                if p.is_file():
                    if key == "dhxml":
                        dhxml = p
                    else:
                        quant = p
    if dhxml is None:
        found = sorted(build_root.glob("*.dhxml"))
        started = [p for p in found if p.name.lower().startswith("buildstarted")]
        dhxml = (started or found or [None])[0]
    if quant is None:
        from ohpal.ampm.batch import _looks_like_quant

        quant = next((p for p in sorted(build_root.glob("*.csv"))
                      if _looks_like_quant(p)), None)
    return dhxml, quant


class TemplateWorker(QObject):
    """Writes one build's samples-template workbook ("Create Excel from AMPM").

    With a BuildStarted .dhxml the template is the full one (part bounds, plus
    QuantAM process parameters when a parts CSV is there too); with only a
    QuantAM parts CSV it is the reduced, point-based one. Emits
    ``(out_path, kind, n_parts)`` with kind "full" or "reduced"."""

    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, build_root, out_path) -> None:
        super().__init__()
        self._build_root = Path(build_root)
        self._out = Path(out_path)

    @pyqtSlot()
    def run(self) -> None:
        try:
            dhxml, quant = find_build_inputs(self._build_root)
            if dhxml is None and quant is None:
                self.error.emit(
                    "This folder has no BuildStarted .dhxml and no QuantAM parts "
                    "CSV, so there is nothing to build the Excel from.")
                return
            from ohpal.ampm import template

            self._out.parent.mkdir(parents=True, exist_ok=True)
            if dhxml is not None:
                template.make_template(dhxml, self._out, quant=quant)
                kind = "full"
            else:
                template.make_template_from_quant(
                    quant, self._out, build_id=self._build_root.name)
                kind = "reduced"
        except SystemExit as exc:  # ohpal helpers can call sys.exit()
            self.error.emit(f"Aborted: {exc}")
        except Exception as exc:  # noqa: BLE001 — a clear one-line reason
            self.error.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.finished.emit((self._out, kind))


class DbscanWorker(QObject):
    """DBSCAN part assignment, off the UI thread — the expensive option.

    Clusters every point of the built layers in 3D (chunked DBSCAN), matches
    each cluster to the nearest part of the QuantAM parts CSV, and emits one
    label per assigned point: a ``(layer, Start time, part_id)`` frame the
    DataStore joins onto queries (``set_part_assignment(..., method="labels")``).
    Points DBSCAN calls noise, or whose cluster matches no part, get no label.

    The labels are cached beside the DataStore with the settings that produced
    them, so reopening a build reads them back instead of clustering again;
    ``force`` (a rebuild) always re-clusters. The STL mask is applied first when
    the build has an STL, as off-part points otherwise muddy the clusters.
    Emits ``(labels, info)``; ``info`` has n_parts / n_points / n_labelled /
    from_cache.
    """

    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, store, config: dict, layers, *, thickness: float,
                 force: bool) -> None:
        super().__init__()
        self._store = store
        self._config = dict(config or {})
        self._layers = sorted(int(L) for L in layers)
        self._thickness = thickness
        self._force = force

    def _params(self) -> dict:
        c = self._config
        return {
            "version": 1,
            "layers": self._layers,
            "parts_csv": str(c.get("PARTS_CSV") or ""),
            "stl": str(c.get("STL") or ""),
            "eps_xy": c.get("EPS_XY", 0.3),
            "eps_z": c.get("EPS_Z", 0.06),
            "min_samples": c.get("MIN_SAMPLES", 10),
            "layers_per_chunk": c.get("LAYERS_PER_CHUNK", 11),
            "overlap_layers": c.get("OVERLAP_LAYERS"),
            "layer_thickness": self._thickness,
        }

    @pyqtSlot()
    def run(self) -> None:
        import json

        try:
            import polars as pl

            cache = Path(self._store.cache_dir)
            labels_path = cache / "dbscan_part_labels.parquet"
            meta_path = cache / "dbscan_part_labels.json"
            params = self._params()
            if not self._force and labels_path.is_file() and meta_path.is_file():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except ValueError:
                    meta = {}
                if meta.get("params") == json.loads(json.dumps(params)):
                    info = dict(meta.get("info") or {}, from_cache=True)
                    # glob=False: build folders are often named like
                    # "[3] Export Packets", which Polars reads as a wildcard.
                    self.finished.emit(
                        (pl.read_parquet(labels_path, glob=False), info))
                    return

            parts_csv = self._config.get("PARTS_CSV")
            if not parts_csv:
                self.error.emit("DBSCAN part assignment needs a parts CSV.")
                return
            from ohpal.ampm.clustering import cluster_dbscan_chunked
            from ohpal.ampm.parts import (
                QuantAMParts, apply_part_id_map, compute_part_id_map)

            # Only what clustering needs (layer + Z ride along), and only the
            # layers already in the DataStore — never trigger a conversion here.
            df = self._store.query(
                layers=list(self._layers),
                columns=["Demand X", "Demand Y", "Start time"])
            n_points = df.height
            stl = self._config.get("STL")
            if stl:
                from ohpal.ampm.masking import apply_mask, build_mask

                mask = build_mask(
                    stl, self._layers, layer_thickness=self._thickness,
                    cache_path=cache / "dbscan_mask.pkl")
                masked = apply_mask(df, mask)
                if masked.height:  # an STL that misses these layers masks
                    df = masked    # everything away — then cluster unmasked
            clustered = cluster_dbscan_chunked(
                df,
                eps_xy=params["eps_xy"], eps_z=params["eps_z"],
                min_samples=params["min_samples"], mode="3d",
                layers_per_chunk=params["layers_per_chunk"],
                overlap_layers=params["overlap_layers"],
                layer_thickness=self._thickness, verbose=False,
            )
            parts = QuantAMParts.from_path(parts_csv).parent_parts()
            mapping = compute_part_id_map(clustered, parts, verbose=False)
            labels = (
                apply_part_id_map(clustered, mapping)
                .filter(pl.col("part_id").is_not_null())
                .select(["layer", "Start time", "part_id"])
                .unique(subset=["layer", "Start time"], keep="first",
                        maintain_order=True)
            )
            if labels.is_empty():
                self.error.emit(
                    "DBSCAN found no cluster that matches a part of the parts "
                    "CSV. The clustering settings may need tuning for this "
                    "build (config.toml, [clustering] eps_xy / eps_z / "
                    "min_samples).")
                return
            info = {
                "n_parts": labels["part_id"].n_unique(),
                "n_points": n_points,
                "n_labelled": labels.height,
                "from_cache": False,
            }
            labels.write_parquet(labels_path)
            meta_path.write_text(
                json.dumps({"params": params, "info": info}), encoding="utf-8")
        except SystemExit as exc:  # ohpal helpers can call sys.exit()
            self.error.emit(f"Aborted: {exc}")
        except MemoryError:
            self.error.emit(
                "Ran out of memory while clustering. Try fewer layers per chunk "
                "(config.toml, [clustering] layers_per_chunk) or a smaller scope.")
        except Exception as exc:  # noqa: BLE001 — a clear one-line reason
            self.error.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.finished.emit((labels, info))


class QueryWorker(QObject):
    """Runs ``DataStore.query`` off the UI thread (Stage 1: query path only).

    The first query of an uncached layer bakes that layer's parquet, which is
    why this runs in a thread. Progress is coarse (query is a single ohpal
    call); finer per-layer progress arrives with the build_cache work later.
    """

    progress = pyqtSignal(int, str)
    finished = pyqtSignal(object)  # QueryResult
    error = pyqtSignal(str)

    def __init__(
        self,
        store: Any,
        layers: tuple[int, int],
        *,
        columns: list[str] | None = None,
        row_cap: int | None = None,
        sample_to: int | None = None,
    ) -> None:
        super().__init__()
        self._store = store
        self._layers = layers
        self._columns = columns
        self._row_cap = row_cap
        self._sample_to = sample_to

    @pyqtSlot()
    def run(self) -> None:
        try:
            lo, hi = self._layers
            self.progress.emit(0, f"Querying layer {lo}…")
            df = self._store.query(
                layers=self._layers, columns=self._columns,
                sample_to=self._sample_to,
            )
            total = df.height
            if self._row_cap is not None and total > self._row_cap:
                df = df.head(self._row_cap)
            self.progress.emit(100, "Loaded")
            self.finished.emit(
                QueryResult(
                    df=df,
                    total_rows=total,
                    shown_rows=df.height,
                    layers=self._layers,
                )
            )
        except SystemExit as exc:  # ohpal config helpers can call sys.exit()
            self.error.emit(f"Load aborted: {exc}")
        except Exception:  # noqa: BLE001 - surface any failure as a message
            self.error.emit(traceback.format_exc())


class MaskWorker(QObject):
    """Builds the STL layer mask off the UI thread.

    Slicing the mesh at every layer is heavy, so it runs here rather than
    freezing the window. ``build_mask`` caches the result to a pickle keyed on
    the STL content + layer set + thickness, so a rebuild with the same inputs
    is cheap. Independent of the parquet cache (it only reads the STL), so it is
    safe to run in parallel with a query/cache build on its own thread. Emits the
    ``Mask`` dict (layer number -> 2D polygon).
    """

    finished = pyqtSignal(object)  # Mask: dict[int, shapely polygon]
    error = pyqtSignal(str)

    def __init__(
        self, stl_path, layers, *, layer_thickness: float, cache_path
    ) -> None:
        super().__init__()
        self._stl_path = stl_path
        self._layers = list(layers)
        self._thickness = layer_thickness
        self._cache_path = cache_path

    @pyqtSlot()
    def run(self) -> None:
        try:
            from ohpal.ampm.masking import build_mask

            mask = build_mask(
                self._stl_path,
                self._layers,
                layer_thickness=self._thickness,
                cache_path=self._cache_path,
            )
        except SystemExit as exc:  # ohpal helpers can call sys.exit()
            self.error.emit(f"Mask build aborted: {exc}")
        except Exception:  # noqa: BLE001 - surface any failure as a message
            self.error.emit(traceback.format_exc())
        else:
            self.finished.emit(mask)


class CacheWorker(QObject):
    """Builds the parquet cache off-thread, one layer at a time.

    We drive the per-layer loop ourselves (``build_cache([L], force=…)`` each),
    rather than scraping ``verbose`` output, so progress is real and the build
    can be cancelled between layers. ``build_cache`` skips up-to-date layers
    quickly when ``force`` is False, so "build missing" is cheap.
    """

    progress = pyqtSignal(int, int, int)  # done, total, layer
    finished = pyqtSignal(int)  # number of layers (re)built
    error = pyqtSignal(str)

    def __init__(self, store: Any, layers: list[int], *, force: bool) -> None:
        super().__init__()
        self._store = store
        self._layers = list(layers)
        self._force = force
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @pyqtSlot()
    def run(self) -> None:
        try:
            total = len(self._layers)
            built = 0
            for i, layer in enumerate(self._layers, start=1):
                if self._cancelled:
                    break
                self._store.build_cache(
                    layers=[layer], force=self._force, verbose=False
                )
                built += 1
                self.progress.emit(i, total, layer)
            self.finished.emit(built)
        except SystemExit as exc:
            self.error.emit(f"Build aborted: {exc}")
        except Exception:  # noqa: BLE001
            self.error.emit(traceback.format_exc())
