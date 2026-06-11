"""
Streaming STL slicer for meshes too large to load into memory.

This module streams the
binary STL in bounded chunks, intersects each triangle with the layer
planes it crosses, spills the resulting 2D segments to per-layer-bucket
temp files, then stitches each layer's segments into oriented rings and
assembles shapely polygons (outers CCW, holes CW).

Output format matches ``ampm.masking.build_mask``:
``dict[layer_number, Polygon | MultiPolygon]``.
"""

from __future__ import annotations

import shutil
import struct
import tempfile
from pathlib import Path
from typing import Iterable

import numpy as np
import shapely
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

# Binary STL triangle record: normal(3f4) + 3 vertices(9f4) + attribute(u2)
_TRI_DTYPE = np.dtype(
    [("normal", "<f4", (3,)), ("verts", "<f4", (3, 3)), ("attr", "<u2")]
)
_HEADER_BYTES = 84
_RECORD_BYTES = 50
_PLANE_EPS = 1e-6
_QUANT = 1e-4

_MAX_EXPANDED_ROWS = 1_000_000


def slice_stl_streaming(
    stl_path: str | Path,
    layers: Iterable[int],
    layer_thickness: float,
    *,
    chunk_triangles: int = 500_000,
    layers_per_bucket: int = 64,
    tmp_dir: str | Path | None = None,
    verbose: bool = True,
) -> dict[int, BaseGeometry]:
    """
    Slice an STL at layer * layer_thickness for each
    requested layer, with memory bounded by chunk_triangles.

    Returns dict{layer_number: Polygon | MultiPolygon}
    """
    stl_path = Path(stl_path)
    layer_list = np.array(sorted(set(int(L) for L in layers)), dtype=np.int64)
    if layer_list.size == 0:
        raise ValueError("No layers requested.")
    plane_z = layer_list * float(layer_thickness) + _PLANE_EPS

    n_tri = _read_binary_stl_header(stl_path)

    work_dir = Path(tempfile.mkdtemp(prefix="stl_slice_", dir=tmp_dir))
    try:
        seg_counts = _pass1_extract_segments(
            stl_path,
            n_tri,
            plane_z,
            work_dir,
            chunk_triangles=chunk_triangles,
            layers_per_bucket=layers_per_bucket,
            verbose=verbose,
        )
        mask = _pass2_build_polygons(
            work_dir,
            layer_list,
            layers_per_bucket=layers_per_bucket,
            verbose=verbose,
        )
        if verbose:
            print(
                f"  [stl_stream] sliced {n_tri:,} triangles -> "
                f"{seg_counts:,} segments -> geometry on "
                f"{len(mask)}/{layer_list.size} layers"
            )
        return mask
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _read_binary_stl_header(stl_path: Path) -> int:
    size = stl_path.stat().st_size
    with stl_path.open("rb") as f:
        head = f.read(_HEADER_BYTES)
    if len(head) < _HEADER_BYTES:
        raise ValueError(f"{stl_path}: too small")
    if head[:5].lower() == b"solid" and b"\x00" not in head:
        raise ValueError("Streaming slicer only supports binary STL.")
    (n_tri,) = struct.unpack("<I", head[80:84])
    expected = _HEADER_BYTES + n_tri * _RECORD_BYTES
    if expected != size:
        raise ValueError(
            f"{stl_path}: header declares {n_tri:,} triangles "
            f"(expects {expected:,} bytes) but file is {size:,} bytes."
        )
    if n_tri == 0:
        raise ValueError(f"{stl_path}: STL contains zero triangles.")
    return n_tri


def _pass1_extract_segments(
    stl_path: Path,
    n_tri: int,
    plane_z: np.ndarray,
    work_dir: Path,
    *,
    chunk_triangles: int,
    layers_per_bucket: int,
    verbose: bool,
) -> int:
    total_segments = 0
    done = 0
    with stl_path.open("rb") as f:
        f.seek(_HEADER_BYTES)
        while done < n_tri:
            count = min(chunk_triangles, n_tri - done)
            tris = np.fromfile(f, dtype=_TRI_DTYPE, count=count)
            if tris.size == 0:
                break
            verts = tris["verts"]
            del tris

            vz = verts[:, :, 2]
            i0 = np.searchsorted(plane_z, vz.min(axis=1), side="left")
            i1 = np.searchsorted(plane_z, vz.max(axis=1), side="right")
            reps = (i1 - i0).clip(min=0)
            bounds = _batch_bounds(np.cumsum(reps), _MAX_EXPANDED_ROWS)
            for a, b in bounds:
                segs, plane_idx = _intersect_chunk(verts[a:b], plane_z)
                if segs.shape[0]:
                    _spill_segments(segs, plane_idx, work_dir, layers_per_bucket)
                    total_segments += segs.shape[0]
            done += count
            if verbose:
                print(
                    f"  [stl_stream] [{done:,}/{n_tri:,}] triangles "
                    f"({total_segments:,} segments)"
                )
    return total_segments


def _batch_bounds(cum_rows: np.ndarray, cap: int) -> list[tuple[int, int]]:
    """Split [0, len()] into slices whose expanded-row totals stay under cap."""
    bounds = []
    start = 0
    base = 0
    n = len(cum_rows)
    while start < n:
        end = int(np.searchsorted(cum_rows, base + cap, side="right"))
        end = max(end, start + 1)
        bounds.append((start, min(end, n)))
        start = min(end, n)
        base = cum_rows[start - 1]

    return bounds


def _intersect_chunk(
    verts: np.ndarray, plane_z: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """
    Intersect a chunk of triangles with the horizontal slice planes.

    verts: (n_tris, 3 vertices, 3 coords) float32.

    Returns: tuple(segments, plane_of_segment)`` where ``segments`` is
    (n_segments, 4) float32 rows of [x1, y1, x2, y2] and ``plane_of_segment``
    is (n_segments,) int32 indices into ``plane_z``. Each segment is ordered
    so that material lies to its LEFT, which makes outer rings come out CCW
    and hole rings CW when stitched.
    """
    verts = verts.astype(np.float32, copy=False)

    vert_z = verts[:, :, 2]
    tri_z_min = vert_z.min(axis=1)
    tri_z_max = vert_z.max(axis=1)

    plane_start = np.searchsorted(plane_z, tri_z_min, side="left")
    plane_stop = np.searchsorted(plane_z, tri_z_max, side="right")
    planes_per_tri = (plane_stop - plane_start).clip(min=0)

    n_intersections = int(planes_per_tri.sum())
    if n_intersections == 0:
        return np.empty((0, 4), np.float32), np.empty((0,), np.int32)

    tri_of_row = np.repeat(np.arange(verts.shape[0]), planes_per_tri)
    first_row_of_tri = np.cumsum(planes_per_tri) - planes_per_tri
    nth_plane_of_tri = np.arange(n_intersections) - np.repeat(
        first_row_of_tri, planes_per_tri
    )
    plane_of_row = (np.repeat(plane_start, planes_per_tri) + nth_plane_of_tri).astype(
        np.int64
    )

    tri_verts = verts[tri_of_row]  # (n_rows, 3 vertices, 3 coords)
    slice_z = plane_z[plane_of_row].astype(np.float64)

    height_above_plane = tri_verts[:, :, 2].astype(np.float64) - slice_z[:, None]
    height_above_plane[height_above_plane == 0.0] = 1e-12

    edge_start_vert = np.array([0, 1, 2])
    edge_end_vert = np.array([1, 2, 0])
    start_height = height_above_plane[:, edge_start_vert]
    end_height = height_above_plane[:, edge_end_vert]

    edge_crosses = (start_height * end_height) < 0.0  # (n_rows, 3 edges)

    with np.errstate(divide="ignore", invalid="ignore"):
        pierce_fraction = start_height / (start_height - end_height)
        edge_start_xy = tri_verts[:, edge_start_vert, :2].astype(np.float64)
        edge_end_xy = tri_verts[:, edge_end_vert, :2].astype(np.float64)
        pierce_xy = edge_start_xy + pierce_fraction[:, :, None] * (
            edge_end_xy - edge_start_xy
        )  # (n_rows, 3 edges, 2)

    two_crossing_edges = np.argsort(~edge_crosses, axis=1)[:, :2]
    seg_endpoints = np.take_along_axis(
        pierce_xy, two_crossing_edges[:, :, None], axis=1
    )  # (n_rows, 2 endpoints, 2)

    edge1 = tri_verts[:, 1, :] - tri_verts[:, 0, :]
    edge2 = tri_verts[:, 2, :] - tri_verts[:, 0, :]
    normal_x = edge1[:, 1] * edge2[:, 2] - edge1[:, 2] * edge2[:, 1]
    normal_y = edge1[:, 2] * edge2[:, 0] - edge1[:, 0] * edge2[:, 2]
    left_dir_x = -normal_y.astype(np.float64)
    left_dir_y = normal_x.astype(np.float64)

    seg_vec = seg_endpoints[:, 1, :] - seg_endpoints[:, 0, :]
    points_wrong_way = (seg_vec[:, 0] * left_dir_x + seg_vec[:, 1] * left_dir_y) < 0.0
    seg_endpoints[points_wrong_way] = seg_endpoints[points_wrong_way][:, ::-1, :]

    has_length = (np.abs(seg_vec) > 1e-12).any(axis=1)
    seg_endpoints = seg_endpoints[has_length]
    plane_of_row = plane_of_row[has_length]  # drops edge points

    segments = seg_endpoints.reshape(-1, 4).astype(np.float32)
    return segments, plane_of_row.astype(np.int32)


def _spill_segments(
    segs: np.ndarray,
    plane_idx: np.ndarray,
    work_dir: Path,
    layers_per_bucket: int,
) -> None:
    """Append rows [plane_idx, x1, y1, x2, y2] (f4) to per-bucket files."""
    bucket = plane_idx // layers_per_bucket
    order = np.argsort(bucket, kind="stable")
    bucket = bucket[order]
    rows = np.column_stack([plane_idx[order].astype(np.float32), segs[order]])
    edges = np.flatnonzero(np.diff(bucket)) + 1
    pieces = np.split(rows, edges)
    ids = bucket[np.concatenate([[0], edges])] if rows.shape[0] else []

    for bucket, piece in zip(ids, pieces):
        with (work_dir / f"bucket_{int(bucket):05d}.f32").open("ab") as file:
            piece.tofile(file)


def _pass2_build_polygons(
    work_dir: Path,
    layer_list: np.ndarray,
    *,
    layers_per_bucket: int,
    verbose: bool,
) -> dict[int, BaseGeometry]:
    mask: dict[int, BaseGeometry] = {}
    bucket_files = sorted(work_dir.glob("bucket_*.f32"))
    for n_done, bf in enumerate(bucket_files, 1):
        rows = np.fromfile(bf, dtype=np.float32).reshape(-1, 5)
        plane_idx = rows[:, 0].astype(np.int64)
        order = np.argsort(plane_idx, kind="stable")
        plane_idx = plane_idx[order]
        segs = rows[order, 1:].astype(np.float64)
        edges = np.flatnonzero(np.diff(plane_idx)) + 1
        for piece, pi in zip(
            np.split(segs, edges),
            plane_idx[np.concatenate([[0], edges])] if segs.shape[0] else [],
        ):
            geom = _polygonize_layer(piece)
            if geom is not None and not geom.is_empty:
                mask[int(layer_list[int(pi)])] = geom
        if verbose:
            print(f"  [stl_stream] polygonized bucket {n_done}/{len(bucket_files)}")

    return mask


def _stitch_rings(segs: np.ndarray) -> list[np.ndarray]:
    """Chain directed segments end-to-start into closed rings."""
    quant = np.round(segs / _QUANT).astype(np.int64)  # (M, 4) quantized
    start_keys = list(map(tuple, quant[:, :2]))
    end_keys = list(map(tuple, quant[:, 2:]))

    by_start: dict[tuple, list[int]] = {}

    for i, k in enumerate(start_keys):
        by_start.setdefault(k, []).append(i)

    used = np.zeros(segs.shape[0], dtype=bool)
    rings: list[np.ndarray] = []

    for i0 in range(segs.shape[0]):
        if used[i0]:
            continue
        chain = [i0]
        used[i0] = True
        cur_end = end_keys[i0]
        ring_start = start_keys[i0]
        while cur_end != ring_start:
            nxt = None
            for j in by_start.get(cur_end, ()):
                if not used[j]:
                    nxt = j
                    break
            if nxt is None:
                break
            used[nxt] = True
            chain.append(nxt)
            cur_end = end_keys[nxt]
        if cur_end == ring_start and len(chain) >= 3:
            rings.append(segs[chain][:, :2])  # start point of each segment

    return rings


def _polygonize_layer(segs: np.ndarray) -> BaseGeometry | None:
    rings = _stitch_rings(segs)
    if not rings:
        return None

    outers: list[np.ndarray] = []
    holes: list[np.ndarray] = []
    for r in rings:
        x, y = r[:, 0], r[:, 1]
        area2 = float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))
        if abs(area2) < 1e-12:
            continue
        (outers if area2 > 0 else holes).append(r)

    if not outers:
        return None

    outer_polys = [Polygon(o) for o in outers]
    hole_lists: list[list[np.ndarray]] = [[] for _ in outer_polys]
    if holes:
        tree = STRtree(outer_polys)
        for h in holes:
            pt = shapely.points(h[0, 0], h[0, 1])
            cands = tree.query(pt, predicate="intersects")
            best, best_area = None, np.inf
            for ci in np.atleast_1d(cands):
                cp = outer_polys[int(ci)]
                if cp.area < best_area and cp.contains(pt):
                    best, best_area = int(ci), cp.area
            if best is not None:
                hole_lists[best].append(h)

    polys = [
        shapely.make_valid(Polygon(o, holes=hl)) for o, hl in zip(outers, hole_lists)
    ]
    geom = shapely.union_all(polys)
    if isinstance(geom, (Polygon, MultiPolygon)) and not geom.is_empty:
        return geom

    geom = shapely.union_all(
        [g for g in shapely.get_parts(geom) if isinstance(g, (Polygon, MultiPolygon))]
    )
    return geom if not geom.is_empty else None
