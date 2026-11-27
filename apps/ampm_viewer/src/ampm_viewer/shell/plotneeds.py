"""What a plot needs from the data: the columns it draws, and the source
columns its query must bring for those to be made.

A plot holds two frames: the rows of its span as queried (``raw``, kept so a
column change can re-shape it without querying again) and the shaped rows it
draws. Holding every column of the build in both is what makes many open
plots expensive, so:

- the query asks only for the **source columns** the plot depends on: the
  ones it draws and filters on, followed back through the calculated columns
  that make them (a calculation needs all its rows, so ``raw`` keeps every
  row of the span, but only those columns);
- the frame it draws keeps only the **drawn columns** (its axes, colour,
  grouping, and the part / layer shown on hover), and only the rows its
  filter keeps.

When a column change needs a source column a plot's ``raw`` lacks, the plot
queries again (see the window's ``_reshape_plots``). Should the dependencies
ever be missed (a filter that no longer finds its column would be skipped
silently), ``complete`` notices and the plot falls back to every column.
"""

from __future__ import annotations

import re

_BRACKET = re.compile(r"\[([^\[\]]*)\]")


def drawn_columns(spec, renames: dict | None = None) -> list[str]:
    """The (display) columns a plot of ``spec`` reads when it draws: its
    axes, colour and grouping, and the part / layer its hover shows. Some
    may not be columns at all (a histogram's "count", a KDE's "density")."""
    renames = renames or {}
    wanted = [*spec.columns,
              renames.get("part_id", "part_id"), renames.get("layer", "layer")]
    return list(dict.fromkeys(c for c in wanted if c))


def refs(text) -> set[str]:
    """The ``[column]`` names in a formula or condition (``by [a, b]`` too)."""
    out = set()
    for m in _BRACKET.finditer(text or ""):
        for part in m.group(1).split(","):
            part = part.strip()
            if part:
                out.add(part)
    return out


def derivation_refs(d: dict) -> set[str]:
    """The columns a calculated column is made from."""
    kind = d.get("kind", "formula")
    if kind == "label":
        out = set()
        for rule in d.get("rules") or []:
            out |= refs(rule.get("cond"))
        return out
    if kind == "join":
        return {d["key"]} if d.get("key") else set()
    if kind == "cluster":  # matched on the point's keys (source names)
        return {"layer", "Start time"}
    out = refs(d.get("expr"))
    if d.get("group"):
        out.add(d["group"])
    return out


def needed_columns(spec, *, derivations=(), renames=None, filters=()) -> set[str]:
    """Every (display) column the plot depends on: what it draws, what its
    filter reads, and what the calculated ones among those are made from."""
    return depends_on(drawn_columns(spec, renames), derivations=derivations,
                      filters=filters)


def depends_on(columns, *, derivations=(), filters=()) -> set[str]:
    """``columns`` (display names) and every column they depend on: what the
    filters read, and what the calculated ones are made from."""
    need = set(columns)
    for cond in filters or ():
        need |= refs(cond)
    # A calculation may build on an earlier one: walk them last to first.
    for d in reversed(list(derivations or ())):
        if d.get("name") in need:
            need |= derivation_refs(d)
    return need


def source_columns(spec, *, derivations=(), renames=None, filters=(),
                   available=None, extra=()) -> list[str] | None:
    """The source (DataStore) columns a plot's query must bring: its needed
    columns under their original names, plus ``extra`` (inputs of the load
    recipe: mask, correction), of those ``available``. None: every column."""
    return sources_for(
        needed_columns(spec, derivations=derivations, renames=renames,
                       filters=filters),
        derivations=derivations, renames=renames, available=available,
        extra=extra)


def sources_for(needed, *, derivations=(), renames=None, available=None,
                extra=()) -> list[str] | None:
    """The source columns behind ``needed`` (display names, with what they
    depend on already in): original names, calculated columns left out, plus
    ``extra``, of those ``available``. None: every column."""
    renames = renames or {}
    original = {new: old for old, new in renames.items()}
    made = {d.get("name") for d in derivations or ()}
    cols = [original.get(c, c) for c in needed if c not in made]
    cols += list(extra or ())
    if available is not None:
        have = set(available)
        cols = [c for c in cols if c in have]
    cols = sorted(set(cols))
    return cols or None


def trim(df, spec, renames: dict | None = None):
    """``df`` with only the columns the plot draws."""
    keep = [c for c in drawn_columns(spec, renames) if c in df.columns]
    if not keep or len(keep) == len(df.columns):
        return df
    return df.select(keep)


def complete(shaped, spec, *, renames=None, filters=(), known=()) -> bool:
    """Whether a frame shaped from a narrowed query has all it should: every
    drawn column the full data has (``known``: its display columns), and
    every filter condition that the full data could apply."""
    from . import derive

    have, known = set(shaped.columns), set(known or ())
    if any(c in known and c not in have for c in drawn_columns(spec, renames)):
        return False
    for cond in filters or ():
        if not (cond or "").strip():
            continue
        try:
            derive.compile_predicate(cond, list(have))
        except Exception:  # noqa: BLE001 - can't be applied to this frame
            try:
                derive.compile_predicate(cond, list(known))
            except Exception:  # noqa: BLE001 - nor to the full data: it's skipped anyway
                continue
            return False
    return True
