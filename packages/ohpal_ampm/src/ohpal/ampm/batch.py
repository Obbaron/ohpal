"""
Generate one samples-template workbook per build found in a data directory.

Discovery is layout-agnostic: the directory is scanned recursively for build
files (``*.dhxml``) and QuantAM parts exports (``*parts*.csv``). Each CSV is
paired to a dhxml by **position containment** — a CSV belongs to the build whose
bounding boxes contain its parent-part positions — so no filename convention is
assumed. Then, per build:

* dhxml (+ matched CSV) -> full template via :func:`make_template`
  (canonical part_id, bounds, optional parameters).
* CSV with no matching dhxml -> reduced template via
  :func:`make_template_from_quant` (QuantAM-derived part_id, point positions).
* dhxml with no CSV -> template with build columns only.

One ``.xlsx`` is written per build into the output directory, named by build_id.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

from ohpal.core.build import BuildFileError, BuildParts
from ohpal.ampm.parts import QuantAMParts
from ohpal.ampm.template import make_template, make_template_from_quant

__all__ = ["generate_build_templates", "BuildResult"]

log = logging.getLogger("ohpal.ampm.batch")


@dataclass
class BuildResult:
    build_id: str
    out_path: Path | None
    source: str                 # "dhxml+quant" | "dhxml" | "quant"
    n_parts: int
    note: str = ""


def _match_fraction(build: BuildParts, qp: QuantAMParts) -> float:
    """Fraction of a QuantAM export's parent positions that land in build boxes."""
    pp = qp.parent_parts()
    if pp.is_empty():
        return 0.0
    xs = pp["x_center"].cast(pl.Float64, strict=False).to_list()
    ys = pp["y_center"].cast(pl.Float64, strict=False).to_list()
    hits = 0
    for x, y in zip(xs, ys):
        if x is None or y is None:
            continue
        try:
            build.part_at(float(x), float(y))
            hits += 1
        except Exception:
            pass
    return hits / len(xs)


def generate_build_templates(
    data_dir: str | Path,
    out_dir: str | Path,
    *,
    columns=("Hatch Speed", "Hatches Power"),
    rename: dict[str, str] | None = None,
    variant: str = "1",
    match_threshold: float = 0.95,
) -> list[BuildResult]:
    """Discover builds under ``data_dir`` and write one template per build.

    Parameters
    ----------
    data_dir
        Directory scanned recursively for ``*.dhxml`` and ``*parts*.csv``.
    out_dir
        Where the per-build ``.xlsx`` files are written (created if absent).
    columns, rename, variant
        Forwarded to the template builders for the parameter columns.
    match_threshold
        Minimum fraction of a CSV's positions that must fall inside a dhxml's
        boxes to pair them (default 0.95 — a genuine pair contains *all* its
        parts; a lower bar lets different builds that share plate real-estate
        match coincidentally). Below this, the CSV is its own dhxml-less build.

    Returns
    -------
    One :class:`BuildResult` per build, describing what was written.
    """
    data_dir, out_dir = Path(data_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    dhxmls = sorted(data_dir.rglob("*.dhxml"))
    csvs = sorted(p for p in data_dir.rglob("*.csv") if _looks_like_quant(p))
    log.info("found %d dhxml, %d QuantAM CSV under %s", len(dhxmls), len(csvs), data_dir)

    builds: list[tuple[Path, BuildParts]] = []
    for d in dhxmls:
        try:
            builds.append((d, BuildParts.from_dhxml(d)))
        except BuildFileError as e:
            log.warning("skipping unreadable dhxml %s: %s", d, e)

    # Score every CSV against every build; pick each CSV's best build above the
    # threshold. A build keeps only its single best CSV; any other CSV that
    # scored for it falls back to being its own dhxml-less build (never dropped).
    readable_csvs: list[tuple[Path, QuantAMParts]] = []
    for c in csvs:
        try:
            readable_csvs.append((c, QuantAMParts.from_path(c)))
        except Exception as e:
            log.warning("skipping unreadable CSV %s: %s", c, e)

    best_build: dict[Path, tuple[Path, float]] = {}   # csv -> (dhxml, frac)
    for c, qp in readable_csvs:
        scored = [(d, _match_fraction(b, qp)) for d, b in builds]
        if scored:
            d, frac = max(scored, key=lambda t: t[1])
            if frac >= match_threshold:
                best_build[c] = (d, frac)

    # Resolve one CSV per dhxml (highest frac wins ties).
    dhxml_csv: dict[Path, Path] = {}
    for c, (d, frac) in sorted(best_build.items(), key=lambda kv: -kv[1][1]):
        if d not in dhxml_csv:
            dhxml_csv[d] = c
        else:
            log.warning("%s also matched %s but %s is already its pair; treating %s "
                        "as its own build", c.name, d.name, dhxml_csv[d].name, c.name)

    consumed = set(dhxml_csv.values())
    results: list[BuildResult] = []

    # dhxml-backed builds (+ matched CSV, if any)
    for d, b in builds:
        matched_csv = dhxml_csv.get(d)
        bid = b.build_id or d.stem
        out = out_dir / f"{_safe(bid)}.xlsx"
        try:
            make_template(d, out, quant=matched_csv, columns=columns,
                          rename=rename, variant=variant, build_id=bid)
            results.append(BuildResult(bid, out, "dhxml+quant" if matched_csv else "dhxml", len(b)))
        except Exception as e:
            results.append(BuildResult(bid, None, "dhxml", len(b), f"FAILED: {e}"))

    # every CSV not consumed by a dhxml -> reduced (QuantAM-alone) template
    for c, qp in readable_csvs:
        if c in consumed:
            continue
        bid = _build_id_from_csv(c)
        out = out_dir / f"{_safe(bid)}.xlsx"
        try:
            n = qp.parent_parts().height
            make_template_from_quant(qp, out, build_id=bid, columns=columns, rename=rename, variant=variant)
            results.append(BuildResult(bid, out, "quant", n, "no dhxml; QuantAM-derived ids"))
        except Exception as e:
            results.append(BuildResult(bid, None, "quant", 0, f"FAILED: {e}"))

    return results


def _looks_like_quant(path: Path) -> bool:
    """Cheap content sniff: a QuantAM parts export, not just any .csv.

    Identifies by the distinctive export signature (``#,Renishaw`` header and a
    ``Parent Parts`` section) in the first few lines, so discovery doesn't
    depend on the filename containing "parts".
    """
    try:
        with path.open("r", encoding="utf-8-sig", errors="ignore") as f:
            head = "".join(next(f, "") for _ in range(6))
    except OSError:
        return False
    return "Renishaw" in head or "Parent Parts" in head


def _build_id_from_csv(path: Path) -> str:
    """Derive a build id from a QuantAM CSV filename (strip a trailing _parts)."""
    stem = path.stem
    for suffix in ("_parts", " parts", "-parts"):
        if stem.lower().endswith(suffix):
            return stem[: -len(suffix)]
    return stem


def _safe(name: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(name)) or "build"


def main(argv: list[str] | None = None) -> int:
    """CLI: ``python -m ohpal.ampm.batch <data_dir> <out_dir> [--speed-power]``."""
    import argparse

    ap = argparse.ArgumentParser(description="Generate a template workbook per build in a data dir.")
    ap.add_argument("data_dir", help="directory scanned recursively for builds")
    ap.add_argument("out_dir", help="where per-build .xlsx files are written")
    ap.add_argument("--variant", default="1", help="QuantAM variant (default: 1)")
    ap.add_argument("--raw-headers", action="store_true",
                    help="keep QuantAM column names instead of renaming to speed/power")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    rename = None if args.raw_headers else {"Hatch Speed": "speed", "Hatches Power": "power"}
    results = generate_build_templates(args.data_dir, args.out_dir, rename=rename, variant=args.variant)

    print(f"\nGenerated {sum(1 for r in results if r.out_path)} of {len(results)} builds:")
    for r in sorted(results, key=lambda r: r.build_id):
        status = r.out_path.name if r.out_path else f"FAILED ({r.note})"
        print(f"  {r.build_id:28} {r.source:12} {r.n_parts:4} parts  -> {status}")
    return 0 if all(r.out_path for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
