"""Pure column-reference rewriting for renames.

A column rename (``old`` → ``new``) has to update every place a column name is
stored: derived-column definitions (their own name plus any ``[old]`` references
in a formula / label condition / join key / group), row filters, the removed
list, the grid's name-based layout, and open plot specs. These helpers are the
*single* source of truth for that rewrite — pure functions over plain data (no
Qt, no Polars), so they can be tested exhaustively.

``[old]`` references are rewritten token-aware: a bracket group may list several
columns (``by [a, old, b]``), so each comma-separated token is matched whole,
not by substring.
"""

from __future__ import annotations

import re
from dataclasses import replace

_BRACKET = re.compile(r"\[([^\[\]]*)\]")


def rewrite_refs(text: str, old: str, new: str) -> str:
    """Rewrite ``[old]`` column references to ``[new]`` in a DSL string.

    Handles multi-column bracket groups (``by [a, old, b]``) by matching each
    comma-separated token whole. Non-matching tokens are left untouched.
    """
    if not text:
        return text

    def sub(m: re.Match) -> str:
        parts = [p.strip() for p in m.group(1).split(",")]
        parts = [new if p == old else p for p in parts]
        return "[" + ", ".join(parts) + "]"

    return _BRACKET.sub(sub, text)


def resolve_all(text: str, renames) -> str:
    """Rewrite every renamed column (original -> display) in a DSL string.

    Used to run hardcoded example / template text through the rename map so a
    renamed column shows under its current name wherever columns are displayed.
    """
    for orig, disp in (renames or {}).items():
        text = rewrite_refs(text, orig, disp)
    return text


def rename_derivations(derivations, old: str, new: str) -> list[dict]:
    """Return a copy of ``derivations`` with ``old`` renamed to ``new``.

    Updates a derivation's own ``name`` (renaming a derived column), and rewrites
    ``[old]`` references inside ``expr``, each label rule's ``cond``, and the
    plain-name ``group`` / ``key`` fields.
    """
    out = []
    for d in derivations or []:
        d = dict(d)
        if d.get("name") == old:
            d["name"] = new
        if "expr" in d:
            d["expr"] = rewrite_refs(d["expr"], old, new)
        if d.get("group") == old:
            d["group"] = new
        if d.get("key") == old:
            d["key"] = new
        if "rules" in d:
            d["rules"] = [
                {**r, "cond": rewrite_refs(r.get("cond", ""), old, new)}
                for r in d["rules"]
            ]
        out.append(d)
    return out


def rename_filters(filters, old: str, new: str) -> list[str]:
    """Rewrite ``[old]`` in each filter condition string."""
    return [rewrite_refs(f, old, new) for f in (filters or [])]


def rename_names(names, old: str, new: str) -> list[str]:
    """Swap ``old`` for ``new`` in a list of plain column names (removed list,
    grid visual order)."""
    return [new if c == old else c for c in (names or [])]


def rename_name_set(names, old: str, new: str) -> set[str]:
    """Swap ``old`` for ``new`` in a set of plain column names (hidden set)."""
    return {new if c == old else c for c in (names or set())}


def rename_spec(spec, old: str, new: str):
    """Return a copy of a ``PlotSpec`` with any ``old`` channel renamed to
    ``new`` (x / y / z / color). ``None`` channels are left as-is."""
    def f(c):
        return new if c == old else c

    return replace(
        spec,
        x=f(spec.x),
        y=f(spec.y),
        z=f(spec.z) if spec.z else spec.z,
        color=f(spec.color) if spec.color else spec.color,
    )
