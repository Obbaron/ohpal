"""
STL masking of AMPM data

Uses full plate export from QuantAM STL to keep only data points
whose (x, y) falls inside that layer's polygon. Designed for the AMPM workflow
where coordinates are already aligned (build-plate frame) and slicing is
naturally per-layer.

Typical usage
-------------
    from ampm import DataStore
    from ampm.masking import build_mask, apply_mask

    store = DataStore(SOURCE_DIR)
    df = store.query(layers=(101, 200))

    mask = build_mask(
        "parts.stl",
        layers=range(101, 201),
        layer_thickness=0.03,
        cache_path="parts.mask.pkl",  # optional but recommended
    )
    df_part_only = apply_mask(df, mask)

The mask is a dict ``{layer_number: shapely.MultiPolygon}``.  Layers with no
intersection are absent from the dict; those rows are dropped by ``apply_mask``.
"""

from __future__ import annotations

import hashlib
import pickle
from pathlib import Path
from typing import Iterable

import numpy as np
import polars as pl
import shapely
import trimesh
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

Mask = dict[int, BaseGeometry]

# STLs above this size are sliced with the streaming slicer instead of trimesh
LARGE_STL_BYTES = 256 * 2**20  # 256mm


def build_mask(
    stl_path: str | Path,
    layers: Iterable[int],
    layer_thickness: float = 0.03,
    buffer_mm: float = 0.0,
    cache_path: str | Path | None = None,
    force: bool = False,
) -> Mask:
    """
    Slice ``stl_path`` at ``layer_n * layer_thickness`` for each layer and
    return a dict mapping layer number to the 2D mask geometry at that height.

    Parameters
    ----------
    stl_path
        Path to the STL file (binary or ASCII).
    layers
        Layer numbers to slice. Layers with no intersection are silently
        dropped — this is normal for layers above/below the part.
    layer_thickness
        Physical layer thickness in mm. Z for layer N is ``N * layer_thickness``.
    buffer_mm
        Optional polygon buffer applied after slicing.
          > 0 : grow the polygon outward (lenient — include points near the edge)
          < 0 : shrink the polygon inward (strict — exclude near-edge points)
          = 0 : no buffer (default)
    cache_path
        If given, pickle the mask to this path on first build and reload it on
        subsequent calls. The cache is keyed to a hash of (stl content,
        layer_thickness, buffer_mm, layer set) so it is invalidated automatically
        when any of those change.
    force
        If True, ignore any existing cache and rebuild.

    Returns
    -------
    dict[int, shapely geometry]
    """
    stl_path = Path(stl_path)
    if not stl_path.is_file():
        raise FileNotFoundError(f"STL not found:\n{stl_path}")

    layer_list = sorted(set(int(L) for L in layers))
    if not layer_list:
        raise ValueError("No layers requested.")

    cache_key = _cache_key(stl_path, layer_list, layer_thickness, buffer_mm)

    if cache_path is not None:
        cache_path = Path(cache_path)
        if not force and cache_path.is_file():
            cached = _load_cache(cache_path)
            if cached is not None and cached.get("key") == cache_key:
                return cached["mask"]

    if stl_path.stat().st_size > LARGE_STL_BYTES:
        raw_mask = _slice_streaming(stl_path, layer_list, layer_thickness)
    else:
        raw_mask = _slice_trimesh(stl_path, layer_list, layer_thickness)

    mask: Mask = {}
    for layer_n, geom in raw_mask.items():
        if buffer_mm != 0.0:
            geom = geom.buffer(buffer_mm)
            if geom.is_empty:
                continue
        if not isinstance(geom, (Polygon, MultiPolygon)):
            continue
        mask[layer_n] = geom

    if cache_path is not None:
        _save_cache(cache_path, {"key": cache_key, "mask": mask})

    return mask


def _slice_trimesh(
    stl_path: Path, layer_list: list[int], layer_thickness: float
) -> Mask:
    """In-memory slicing via trimesh."""
    mesh = trimesh.load_mesh(stl_path)
    if not isinstance(mesh, trimesh.Trimesh):
        raise TypeError(
            f"Expected a single mesh from {stl_path}, got {type(mesh).__name__}. "
        )
    if mesh.is_empty or mesh.bounds is None or len(mesh.faces) == 0:
        raise ValueError(f"trimesh loaded {stl_path} as an EMPTY mesh.")

    heights = np.array([L * layer_thickness for L in layer_list], dtype=float)

    # section_multiplane is much faster than calling section() in a loop.
    # plane_origin is the *base* point; heights are offsets along plane_normal.
    sections = mesh.section_multiplane(
        plane_origin=[0.0, 0.0, 0.0],
        plane_normal=[0.0, 0.0, 1.0],
        heights=heights,
    )

    mask: Mask = {}
    for layer_n, section in zip(layer_list, sections):
        if section is None:
            continue  # plane misses the mesh
        try:
            polys = list(section.polygons_full)
        except ModuleNotFoundError as e:
            raise ModuleNotFoundError(
                f"trimesh is missing an optional dependency required for "
                f"slicing: {e.name}. Install everything trimesh needs with:\n"
                f'    pip install "trimesh[easy]"\n'
                f"or install the missing module directly: pip install {e.name}"
            ) from e
        if not polys:
            continue
        mask[layer_n] = polys[0] if len(polys) == 1 else MultiPolygon(polys)
    return mask


def _slice_streaming(
    stl_path: Path, layer_list: list[int], layer_thickness: float
) -> Mask:
    """Constant-memory slicing for huge STL files (e.g. lattice builds)."""
    try:
        from .stl_stream import slice_stl_streaming
    except ImportError:  # running as a plain module outside the package
        from stl_stream import slice_stl_streaming

    return slice_stl_streaming(stl_path, layer_list, layer_thickness)


def apply_mask(
    df: pl.DataFrame,
    mask: Mask,
    x_col: str = "Demand X",
    y_col: str = "Demand Y",
    layer_col: str = "layer",
) -> pl.DataFrame:
    """
    Return only the rows of ``df`` that fall inside the mask polygon for
    their respective layer.

    Rows whose layer is not in the mask (e.g. layers above or below the part,
    or layers we never sliced) are dropped.

    Memory: builds a single boolean keep-array of length N alongside the
    input DataFrame; no per-layer DataFrame copies are made.

    Parameters
    ----------
    df
        DataFrame with columns ``x_col``, ``y_col``, ``layer_col``.
    mask
        Output of ``build_mask``.
    x_col, y_col, layer_col
        Column names. Defaults match the DataStore output.
    """
    for c in (x_col, y_col, layer_col):
        if c not in df.columns:
            raise KeyError(f"Column {c!r} not in DataFrame")

    if df.is_empty():
        return df

    layers = df[layer_col].to_numpy()
    xs = df[x_col].to_numpy()
    ys = df[y_col].to_numpy()
    keep = np.zeros(df.height, dtype=bool)

    for layer_n, geom in mask.items():
        idx = np.flatnonzero(layers == layer_n)
        if idx.size == 0:
            continue
        shapely.prepare(geom)
        points = shapely.points(xs[idx], ys[idx])
        inside = shapely.contains(geom, points)
        keep[idx] = inside

    return df.filter(pl.Series(keep))


def stl_hash(stl_path: str | Path) -> str:
    """SHA-256 fingerprint of the STL file contents."""
    stl = Path(stl_path)
    size = stl.stat().st_size
    hash = hashlib.sha256()
    with stl.open("rb") as file:
        if size <= LARGE_STL_BYTES:
            for chunk in iter(lambda: file.read(1 << 20), b""):
                hash.update(chunk)
        else:
            sample = 8 * 2**20
            hash.update(f"sampled:{size}:".encode())
            for offset in sorted({0, max(0, size // 2), max(0, size - sample)}):
                file.seek(offset)
                hash.update(file.read(sample))
    return hash.hexdigest()


def _cache_key(
    stl_path: Path,
    layers: list[int],
    layer_thickness: float,
    buffer_mm: float,
) -> str:
    """Hash STL contents + slicing params so the cache invalidates correctly."""
    hash = hashlib.sha256(stl_hash(stl_path).encode())
    hash.update(repr((layers, layer_thickness, buffer_mm)).encode())
    return hash.hexdigest()


def _save_cache(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)


def _load_cache(path: Path) -> dict | None:
    try:
        with path.open("rb") as f:
            return pickle.load(f)
    except Exception:
        return None
