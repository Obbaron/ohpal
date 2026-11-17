"""Plots that outlive the session: a build's own plots, and the plot library.

A **plot record** is a plain, versioned dict that describes one plot: its
spec (kind, columns, toolbar options), the layers it covers, the filter it
was made with, its title and its whole look (``PlotTab.appearance``).

- A build's own plots are kept as records in ``plots.json`` in the build's
  cache folder and reopen with the build, drawn again from its current data
  (live). Rebuilding the DataStore clears them, like the rest of the
  per-build state.
- The **plot library** keeps *frozen* plots: the record plus the rows the
  plot draws, in one ``.ampmplot`` file (a zip of ``plot.json`` and
  ``data.parquet``). A frozen plot always shows the numbers of the build it
  came from, so plots of different builds can be opened side by side, with
  or without a build open. The library is a folder (Documents/AMPM
  Viewer/Plots by default, changeable in Settings, for example to a shared
  team folder).
"""

from __future__ import annotations

import io
import json
import math
import zipfile
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QStandardPaths

from .settings import app_settings

FORMAT = "ampm-plot"
VERSION = 1
SUFFIX = ".ampmplot"
FILE_FILTER = f"AMPM plots (*{SUFFIX})"
BIG_BYTES = 100 * 1024 * 1024   # warn before saving a frozen plot this large
_BUILD_FILE = "plots.json"


class LibraryError(ValueError):
    """A plot file that can't be read or isn't an AMPM plot."""


# -- records ------------------------------------------------------------
def _jsonable(value):
    """Plain JSON types only (tuples to lists, numpy scalars to numbers,
    anything else to its text)."""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return int(value)
    try:
        f = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f if math.isfinite(f) else None


def record(tab) -> dict:
    """The record of a plot tab, as it is now."""
    return _jsonable({
        "spec": asdict(tab.spec),
        "span": list(tab.span),
        "title": tab.title,
        "row_filter": list(tab.row_filter or []),
        "appearance": tab.appearance(),
    })


def spec_from(data: dict):
    """A ``PlotSpec`` from a record's spec (fields it doesn't know are
    dropped, missing ones take their defaults)."""
    from .plotspec import PLOT_KINDS, PlotSpec

    if not isinstance(data, dict) or data.get("kind") not in PLOT_KINDS:
        raise LibraryError("it isn't a plot this version can draw")
    known = {f.name for f in fields(PlotSpec)}
    try:
        return PlotSpec(**{k: v for k, v in data.items() if k in known})
    except TypeError as exc:
        raise LibraryError(f"its plot settings are incomplete ({exc})") from exc


def span_from(data) -> tuple:
    try:
        mode, lo, hi = data
    except (TypeError, ValueError):
        return ("all", None, None)
    if mode not in ("all", "range", "single"):
        return ("all", None, None)
    return (mode, lo, hi)


# -- a build's own plots (live, reopened with the build) -----------------
def save_build_plots(cache_dir, records: list) -> None:
    """Keep these records as the build's plots (best effort)."""
    try:
        path = Path(cache_dir)
        path.mkdir(parents=True, exist_ok=True)
        (path / _BUILD_FILE).write_text(json.dumps(
            {"format": FORMAT, "version": VERSION, "plots": records}),
            encoding="utf-8")
    except OSError:
        pass


def load_build_plots(cache_dir) -> list[dict]:
    """The build's saved plot records ([] when none or unreadable)."""
    try:
        data = json.loads((Path(cache_dir) / _BUILD_FILE).read_text(
            encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if (not isinstance(data, dict) or data.get("format") != FORMAT
            or data.get("version") != VERSION):
        return []
    return [r for r in data.get("plots") or [] if isinstance(r, dict)]


def clear_build_plots(cache_dir) -> None:
    try:
        (Path(cache_dir) / _BUILD_FILE).unlink(missing_ok=True)
    except OSError:
        pass


# -- the library folder ----------------------------------------------------
_FOLDER_KEY = "plots/library_folder"


def default_folder() -> Path:
    """``Documents/AMPM Viewer/Plots``, beside the macro folder."""
    docs = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.DocumentsLocation)
    return Path(docs or Path.home()) / "AMPM Viewer" / "Plots"


def folder() -> Path:
    chosen = app_settings().value(_FOLDER_KEY, "") or ""
    return Path(chosen) if chosen else default_folder()


def is_default_folder() -> bool:
    return not (app_settings().value(_FOLDER_KEY, "") or "")


def set_folder(path) -> None:
    """Choose the library folder (None, or the default: back to it)."""
    s = app_settings()
    if path is None or Path(path) == default_folder():
        s.remove(_FOLDER_KEY)
    else:
        s.setValue(_FOLDER_KEY, str(Path(path)))


def ensure_folder() -> Path | None:
    """The library folder, created if needed; None when it can't be reached."""
    path = folder()
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return path if path.is_dir() else None
    return path


# -- frozen plots --------------------------------------------------------------
@dataclass
class Entry:
    """A plot in the library, as listed (read from its ``plot.json`` only)."""
    path: str
    title: str
    kind: str
    build: str
    saved: str     # ISO time
    rows: int
    size: int      # bytes on disk

    @property
    def saved_text(self) -> str:
        return when(self.saved)


def when(iso: str) -> str:
    """A saved time, for people (16 Nov 2026 14:03)."""
    try:
        return datetime.fromisoformat(iso).strftime("%d %b %Y %H:%M")
    except (TypeError, ValueError):
        return str(iso or "")


def plot_columns(spec, columns, renames: dict | None = None) -> list[str]:
    """The columns a plot of ``spec`` reads, of ``columns`` (its axes,
    colour, grouping, and the part / layer shown on hover)."""
    renames = renames or {}
    wanted = [spec.x, spec.y, spec.z, spec.color, spec.group_by,
              renames.get("part_id", "part_id"), renames.get("layer", "layer")]
    have = set(columns)
    return list(dict.fromkeys(c for c in wanted if c and c in have))


def frozen_info(tab, *, build: str, renames: dict, layers: list,
                rows: int) -> dict:
    """The ``plot.json`` of a frozen plot of ``tab``."""
    from .. import __version__

    rec = record(tab)
    return _jsonable({
        "format": FORMAT, "version": VERSION, "app_version": __version__,
        **rec,
        "build": build,
        "saved": datetime.now().isoformat(timespec="seconds"),
        "renames": dict(renames or {}),
        "layer_column": (renames or {}).get("layer", "layer"),
        "layers": list(layers or []),
        "rows": int(rows),
    })


def save_frozen(path, info: dict, df) -> int:
    """Write a frozen plot (its info and its rows); returns the file's
    size. ``df`` holds only the rows and columns the plot draws."""
    buf = io.BytesIO()
    df.write_parquet(buf, compression="zstd")
    path = Path(path)
    tmp = path.with_name(path.name + ".part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:
        z.writestr("plot.json", json.dumps(info, indent=1))
        z.writestr("data.parquet", buf.getvalue())
    tmp.replace(path)  # never leave half a file under the real name
    return path.stat().st_size


def _read_info(z: zipfile.ZipFile, path) -> dict:
    try:
        info = json.loads(z.read("plot.json").decode("utf-8"))
    except KeyError:
        raise LibraryError(f"{Path(path).name} isn't an AMPM plot") from None
    except ValueError as exc:
        raise LibraryError(f"{Path(path).name} is damaged ({exc})") from exc
    if not isinstance(info, dict) or info.get("format") != FORMAT:
        raise LibraryError(f"{Path(path).name} isn't an AMPM plot")
    if info.get("version") != VERSION:
        raise LibraryError(
            f"{Path(path).name} was saved by a newer version of the app "
            f"(plot format {info.get('version')})")
    return info


def read_info(path) -> dict:
    """A frozen plot's ``plot.json`` (its data is not read)."""
    try:
        with zipfile.ZipFile(path) as z:
            return _read_info(z, path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise LibraryError(f"{Path(path).name} can't be read ({exc})") from exc


def load_frozen(path):
    """A frozen plot: (info, its rows as a DataFrame)."""
    import polars as pl

    try:
        with zipfile.ZipFile(path) as z:
            info = _read_info(z, path)
            data = z.read("data.parquet")
    except KeyError:
        raise LibraryError(f"{Path(path).name} has no data") from None
    except (OSError, zipfile.BadZipFile) as exc:
        raise LibraryError(f"{Path(path).name} can't be read ({exc})") from exc
    try:
        df = pl.read_parquet(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 - any parquet failure
        raise LibraryError(f"{Path(path).name}: its data is damaged ({exc})") from exc
    spec_from(info.get("spec"))  # check it can be drawn
    return info, df


def entries(where=None) -> list[Entry]:
    """The plots in the library folder, newest first (unreadable files are
    left out)."""
    out = []
    try:
        files = [p for p in Path(where or folder()).iterdir()
                 if p.is_file() and p.name.lower().endswith(SUFFIX)]
    except OSError:
        return []
    for p in files:
        try:
            info = read_info(p)
            out.append(Entry(str(p), str(info.get("title") or p.stem),
                             str((info.get("spec") or {}).get("kind", "")),
                             str(info.get("build") or ""),
                             str(info.get("saved") or ""),
                             int(info.get("rows") or 0), p.stat().st_size))
        except (LibraryError, OSError, ValueError, TypeError):
            continue
    out.sort(key=lambda e: e.saved, reverse=True)
    return out


def safe_name(text: str) -> str:
    """``text`` usable as a file name."""
    return "".join(c if (c.isalnum() or c in " -_()") else "_"
                   for c in text).strip() or "plot"


def view_frame(df, spec, span, layer_column: str):
    """What a frozen plot draws now: all its rows, or (a Layer Viewer) the
    layer it is on."""
    import polars as pl

    if spec.is_layer_viewer and layer_column in df.columns and span[1] is not None:
        return df.filter(pl.col(layer_column) == span[1])
    return df
