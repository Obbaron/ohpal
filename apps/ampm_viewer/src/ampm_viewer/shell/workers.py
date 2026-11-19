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

from PyQt6.QtCore import QCoreApplication, QObject, Qt, QThread, pyqtSignal, pyqtSlot

from .state import QueryResult

# Workers whose threads are still winding down (see ``release_after``).
_RETIRING: set = set()


def release_after(thread, worker) -> None:
    """Free ``worker`` on the main thread once ``thread`` has finished.

    Not ``thread.finished.connect(worker.deleteLater)``: that destroys the
    worker on its own thread, where its destructor disconnects it from the
    (Python-wrapped) QThread, and PyQt then waits for the GIL while holding
    one of Qt's connection locks. If the main thread is making a connection
    at that moment (rebuilding a toolbar, say) it holds the GIL and waits on
    the same lock, and the app freezes.

    Instead, the moment the worker reports (``finished`` or ``error``, still
    on its own thread) it hands itself to the main thread, and it is kept
    here until its thread has stopped. Dropping that last reference on the
    main thread then deletes it there."""
    main = QCoreApplication.instance().thread()

    def hand_over(*_args) -> None:
        if worker.thread() is QThread.currentThread():  # once: finished or error
            worker.moveToThread(main)

    direct = Qt.ConnectionType.DirectConnection
    for signal in (worker.finished, worker.error):
        signal.connect(hand_over, direct)
    pair = (thread, worker)
    _RETIRING.add(pair)
    thread.finished.connect(lambda: _RETIRING.discard(pair))


class LoadWorker(QObject):
    """Loads (or creates) a build's config and constructs its DataStore, off the
    UI thread.

    This is where the first ``import ohpal`` happens — which cascades into
    ``polars`` and SciPy and costs about half a second on the first build open
    (scikit-learn and trimesh are imported only when used). Running
    it here keeps the window responsive instead of freezing. Emits
    ``(config, store, source_dir, thickness, elapsed_ms)``; a ``create`` flag
    (decided on the main thread) says whether a missing config should be made.
    """

    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, build_root, *, create: bool, stack=None) -> None:
        super().__init__()
        self._build_root = Path(build_root)
        self._create = create
        self._stack = stack  # (name, step folders): write this stack first

    @pyqtSlot()
    def run(self) -> None:
        t = time.perf_counter()
        try:
            from .stackbuild import is_stack_folder

            if self._stack is not None:
                from ohpal.ampm.stacked import write_stack

                write_stack(self._build_root, *self._stack)
            if is_stack_folder(self._build_root):
                self._load_stack(t)
                return
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

    def _load_stack(self, t: float) -> None:
        """A stacked build: every step's config (made where missing: a step
        is an ordinary build folder) and DataStore, read as one."""
        from ohpal.ampm.stacked import load_stack

        from .stackbuild import stack_config

        store = load_stack(self._build_root, create_configs=True)
        config = stack_config(store)
        self.finished.emit(
            (config, store, self._build_root, store.layer_thickness,
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
    """Writes one build's samples-template workbook (New ▸ Excel template).

    With a BuildStarted .dhxml the template is the full one (part bounds, plus
    QuantAM process parameters when a parts CSV is there too); with only a
    QuantAM parts CSV it is the reduced, point-based one. Emits
    ``(out_path, kind, n_parts)`` with kind "full" or "reduced"."""

    finished = pyqtSignal(object)
    error = pyqtSignal(str)
    NOTHING = ("This folder has no BuildStarted .dhxml and no QuantAM parts "
               "CSV, so there is nothing to build the Excel from.")

    def __init__(self, build_root, out_path) -> None:
        super().__init__()
        self._build_root = Path(build_root)
        self._out = Path(out_path)

    @pyqtSlot()
    def run(self) -> None:
        try:
            dhxml, quant = find_build_inputs(self._build_root)
            if dhxml is None and quant is None:
                self.error.emit(self.NOTHING)
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
    """DBSCAN part assignment: the expensive option, off the UI thread, with
    the clustering itself in a separate process so it can be cancelled.

    Clusters every point of the built layers in 3D (chunked DBSCAN), matches
    each cluster to the nearest part of the QuantAM parts CSV, and emits one
    label per assigned point: a ``(layer, Start time, part_id)`` frame the
    DataStore joins onto queries (``set_part_assignment(..., method="labels")``).
    Points DBSCAN calls noise, or whose cluster matches no part, get no label.

    This thread reads the points (and applies the STL mask when the build has
    one: off-part points muddy the clusters), then hands them to
    ``ampm_viewer.dbscan_job``, run as a separate process. A running scikit-learn
    DBSCAN can't be interrupted from Python, but a process can be stopped at
    once, so ``cancel`` ends it immediately and frees its memory.

    The labels are cached beside the DataStore with the settings that produced
    them, so reopening a build reads them back instead of clustering again;
    ``force`` (a rebuild) always re-clusters. Emits ``progress(text)`` as it
    goes and ``finished((labels, info))``, or ``finished(None)`` when
    cancelled; ``info`` has n_parts / n_points / n_labelled / from_cache.
    """

    progress = pyqtSignal(str)
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
        self._cancelled = False
        self._process = None

    def cancel(self) -> None:
        """Stop now (any thread): the clustering process is ended at once;
        reading the points stops at the next step."""
        self._cancelled = True
        proc = self._process
        if proc is not None and proc.poll() is None:
            proc.kill()

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

        cache = Path(self._store.cache_dir)
        input_path = cache / "dbscan_input.parquet"
        output_path = cache / "dbscan_part_labels.partial.parquet"
        try:
            import polars as pl

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

            # Only what clustering needs (layer + Z ride along), and only the
            # layers already in the DataStore: never trigger a conversion here.
            self.progress.emit("reading points")
            df = self._store.query(
                layers=list(self._layers),
                columns=["Demand X", "Demand Y", "Start time"])
            n_points = df.height
            stl = self._config.get("STL")
            if stl and not self._cancelled:
                from ohpal.ampm.masking import apply_mask, build_mask

                self.progress.emit("masking")
                mask = build_mask(
                    stl, self._layers, layer_thickness=self._thickness,
                    cache_path=cache / "dbscan_mask.pkl", verbose=False)
                masked = apply_mask(df, mask)
                if masked.height:  # an STL that misses these layers masks
                    df = masked    # everything away; then cluster unmasked
            if self._cancelled:
                self.finished.emit(None)
                return
            df.write_parquet(input_path)
            del df

            info = self._cluster(str(input_path), str(output_path), params,
                                 str(parts_csv))
            if info is None:  # cancelled, or an error already reported
                return
            labels = pl.read_parquet(output_path, glob=False)
            info.update(n_points=n_points, from_cache=False)
            labels.write_parquet(labels_path)
            meta_path.write_text(
                json.dumps({"params": params, "info": info}), encoding="utf-8")
        except SystemExit as exc:  # ohpal helpers can call sys.exit()
            self.error.emit(f"Aborted: {exc}")
        except MemoryError:
            self.error.emit(
                "Ran out of memory while reading the points. Try a smaller "
                "layer range.")
        except Exception as exc:  # noqa: BLE001 - a clear one-line reason
            self.error.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.finished.emit((labels, info))
        finally:
            for tmp in (input_path, output_path):
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass

    def _cluster(self, input_path: str, output_path: str, params: dict,
                 parts_csv: str) -> dict | None:
        """Run the clustering process to the end, relaying its progress.
        Returns its info; None when cancelled (``finished(None)`` emitted) or
        failed (``error`` emitted)."""
        cache = Path(input_path).parent
        return run_job_process(self, {
            "input": input_path, "output": output_path, "parts_csv": parts_csv,
            "params": params}, cache, "dbscan_job")


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
        self, stl_path=None, layers=(), *, layer_thickness: float = 0.03,
        cache_path=None, jobs=None,
    ) -> None:
        super().__init__()
        # ``jobs``: one (stl, layers, thickness, cache_path, layer offset)
        # each, merged into one mask keyed by layer + offset (a stacked
        # build's steps); else the one build's STL.
        self._jobs = list(jobs) if jobs is not None else [
            (stl_path, list(layers), layer_thickness, cache_path, 0)]

    @pyqtSlot()
    def run(self) -> None:
        try:
            from ohpal.ampm.masking import build_mask

            mask = {}
            for stl, layers, thickness, cache_path, offset in self._jobs:
                # Quiet: the slicer's own progress lines would go to the
                # terminal and weave through the DataStore build's in the
                # log; the controller logs one line when the mask is ready.
                part = build_mask(
                    stl, list(layers), layer_thickness=thickness,
                    cache_path=cache_path, verbose=False)
                mask.update({int(L) + offset: g for L, g in part.items()})
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

_POLL_S = 0.2   # how often a job's messages and Cancel are checked


def run_job_process(owner, job: dict, folder: Path, stem: str) -> dict | None:
    """Run ``ampm_viewer.dbscan_job`` on ``job`` as a separate process and
    relay its messages through ``owner`` (a worker with ``progress``,
    ``error`` and ``finished`` signals, a ``_cancelled`` flag it checks and a
    ``_process`` it sets so ``cancel`` can end it). The job, progress and log
    files are ``<stem>.json`` / ``.progress`` / ``.log`` in ``folder``.
    Returns the job's info; None when cancelled (``finished(None)`` emitted)
    or failed (``error`` emitted)."""
    import json
    import subprocess

    from ampm_viewer import dbscan_job

    job_path = folder / f"{stem}.json"
    progress_path = folder / f"{stem}.progress"
    log_path = folder / f"{stem}.log"
    progress_path.write_text("", encoding="utf-8")
    job_path.write_text(json.dumps(dict(job, progress=str(progress_path))),
                        encoding="utf-8")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # Windows: no console
    owner.progress.emit("starting")
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            dbscan_job.command(str(job_path)), stdin=subprocess.DEVNULL,
            stdout=log, stderr=log, creationflags=flags)
    owner._process = proc
    try:
        return _relay(owner, proc, progress_path, log_path)
    finally:
        owner._process = None
        if proc.poll() is None:
            proc.kill()
        for tmp in (job_path, progress_path):
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


def _relay(owner, proc, progress_path: Path, log_path: Path) -> dict | None:
    """``run_job_process``'s loop: relay the job's messages until it ends."""
    import json
    import time

    read = 0
    while True:
        if owner._cancelled:
            proc.kill()
            proc.wait(10)
            owner.finished.emit(None)
            return None
        ended = proc.poll() is not None
        text = progress_path.read_text(encoding="utf-8")
        lines, read = text[read:].splitlines(), len(text)
        if lines and not text.endswith("\n"):  # a line half-written
            read -= len(lines.pop())
        for line in lines:
            msg = json.loads(line)
            if msg[0] == "stage":
                owner.progress.emit(msg[1])
            elif msg[0] == "chunk":
                owner.progress.emit(f"clustering chunk {msg[1]} of {msg[2]}")
            elif msg[0] == "error":
                owner.error.emit(msg[1])
                return None
            elif msg[0] == "done":
                proc.wait(30)
                return dict(msg[1])
        if ended:
            if owner._cancelled:
                continue
            tail = ""
            try:
                tail = log_path.read_text(encoding="utf-8").strip().splitlines()[-1]
            except (OSError, IndexError):
                pass
            owner.error.emit(
                "The clustering process stopped unexpectedly (exit "
                f"code {proc.returncode}). It may have run out of "
                "memory: try fewer layers per chunk (config.toml, "
                "[clustering] layers_per_chunk) or a smaller layer "
                "range." + (f"\n\n{tail}" if tail else ""))
            return None
        time.sleep(_POLL_S)


class ClusterWorker(QObject):
    """The Data tab's DBSCAN, off the UI thread, the clustering itself in a
    separate process (``ampm_viewer.dbscan_job``, kind "cluster") so Cancel
    stops it at once.

    Reads the built layers' points (only the columns needed), shapes them as
    the grid is shaped and keeps the rows the filters keep (``shape``, a
    snapshot taken when it started), then clusters on the position and/or the
    chosen columns. Rows missing a value it clusters on are left out. Writes
    ``(layer, Start time, cluster)`` to ``out_path`` (0 = the largest
    cluster, -1 = noise) with a ``.json`` beside it (the settings and the
    result's summary), and emits ``finished((out_path, info))``, or
    ``finished(None)`` when cancelled.

    ``names`` maps what the job reads to this build's (display) columns:
    ``layer``, ``Start time``, and with the position ``Demand X``,
    ``Demand Y`` and ``Z``; ``features`` is ``[(display column, radius)]``.
    """

    progress = pyqtSignal(str)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, store, layers, *, columns, shape, names: dict,
                 features, params: dict, out_path) -> None:
        super().__init__()
        self._store = store
        self._layers = sorted(int(L) for L in layers)
        self._columns = columns
        self._shape = shape
        self._names = dict(names)
        self._features = [(str(c), float(r)) for c, r in features]
        self._params = dict(params)
        self._out = Path(out_path)
        self._cancelled = False
        self._process = None

    def cancel(self) -> None:
        self._cancelled = True
        proc = self._process
        if proc is not None and proc.poll() is None:
            proc.kill()

    @pyqtSlot()
    def run(self) -> None:
        import json

        folder = self._out.parent
        input_path = folder / f"{self._out.stem}.input.parquet"
        output_path = folder / f"{self._out.stem}.partial.parquet"
        try:
            import polars as pl

            folder.mkdir(parents=True, exist_ok=True)
            self.progress.emit("reading points")
            raw = self._store.query(layers=list(self._layers), columns=self._columns)
            if self._cancelled:
                self.finished.emit(None)
                return
            self.progress.emit("applying the filters")
            df = self._shape(raw)
            del raw
            # The job's own names: the keys and position by their source
            # names, the chosen columns as f0, f1, ...
            picks = {self._names[k]: k for k in self._names}
            for i, (col, _r) in enumerate(self._features):
                picks[col] = f"f{i}"
            missing = [c for c in picks if c not in df.columns]
            if missing:
                self.error.emit("These columns are not in the data: "
                                + ", ".join(missing))
                return
            numeric = [job for col, job in picks.items()
                       if job not in ("layer", "Start time")]
            df = df.select([pl.col(c).alias(j) for c, j in picks.items()])
            df = df.with_columns([pl.col(c).cast(pl.Float64) for c in numeric])
            # Only rows with every value it clusters on.
            df = df.filter(pl.all_horizontal(
                [pl.col(c).is_finite() for c in numeric]
                + [pl.col("layer").is_not_null(), pl.col("Start time").is_not_null()]))
            df = df.unique(subset=["layer", "Start time"], keep="first",
                           maintain_order=True)
            if df.is_empty():
                self.error.emit(
                    "There are no rows to cluster: the filters keep none, or "
                    "they have no values in the columns chosen.")
                return
            n_rows = df.height
            df.write_parquet(input_path)
            del df
            if self._cancelled:
                self.finished.emit(None)
                return
            params = dict(self._params,
                          features={f"f{i}": r for i, (_c, r)
                                    in enumerate(self._features)})
            info = run_job_process(self, {
                "kind": "cluster", "input": str(input_path),
                "output": str(output_path), "params": params},
                folder, f"{self._out.stem}.job")
            if info is None:
                return  # cancelled, or an error already reported
            output_path.replace(self._out)
            info["n_points"] = n_rows
            self._out.with_suffix(".json").write_text(
                json.dumps({"settings": self._params, "info": info}),
                encoding="utf-8")
        except SystemExit as exc:  # ohpal helpers can call sys.exit()
            self.error.emit(f"Aborted: {exc}")
        except MemoryError:
            self.error.emit(
                "Ran out of memory while reading the points. Add a filter to "
                "cluster fewer rows.")
        except Exception as exc:  # noqa: BLE001 - a clear one-line reason
            self.error.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.finished.emit((self._out, info))
        finally:
            for tmp in (input_path, output_path):
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
