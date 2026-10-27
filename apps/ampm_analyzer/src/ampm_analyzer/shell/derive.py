"""Row-wise derived columns.

A derived column is a formula over existing columns, evaluated per row and
re-applied to every query result (so it survives layer changes). Columns are
referenced by name inside square brackets, e.g.::

    [MeltVIEW melt pool (mean)] / [LaserVIEW (mean)]

Only arithmetic and a small set of math functions are allowed; the formula is
parsed to an AST and compiled to a Polars expression — never ``eval``-ed.
Derivations are applied in order, so a later one may reference an earlier one.
"""

from __future__ import annotations

import ast
import re
from typing import Any

_TOKEN_RE = re.compile(r"\[([^\[\]]+)\]")


class DeriveError(ValueError):
    """A formula that can't be compiled (bad syntax, unknown column, …)."""


def _functions() -> dict[str, tuple[int, Any]]:
    import polars as pl

    return {
        "abs": (1, lambda a: a.abs()),
        "sqrt": (1, lambda a: a.sqrt()),
        "log": (1, lambda a: a.log()),
        "log10": (1, lambda a: a.log10()),
        "exp": (1, lambda a: a.exp()),
        "sin": (1, lambda a: a.sin()),
        "cos": (1, lambda a: a.cos()),
        "min": (2, lambda a, b: pl.min_horizontal(a, b)),
        "max": (2, lambda a, b: pl.max_horizontal(a, b)),
    }


def compile_expr(text: str, columns) -> Any:
    """Compile a formula string to a Polars expression.

    Raises ``DeriveError`` with a human-readable message on any problem.
    """
    import polars as pl

    text = (text or "").strip()
    if not text:
        raise DeriveError("Expression is empty.")

    known = set(columns)
    mapping: dict[str, str] = {}  # placeholder identifier -> column name

    def _sub(m: re.Match) -> str:
        name = m.group(1)
        if name not in known:
            raise DeriveError(f"Unknown column: {name!r}")
        key = f"_col_{len(mapping)}"
        mapping[key] = name
        return key

    substituted = _TOKEN_RE.sub(_sub, text)
    if "[" in substituted or "]" in substituted:
        raise DeriveError("Unbalanced '[' / ']' in expression.")

    try:
        tree = ast.parse(substituted, mode="eval")
    except SyntaxError as exc:
        raise DeriveError(f"Could not parse expression: {exc.msg}") from exc

    funcs = _functions()

    def build(node):
        if isinstance(node, ast.Expression):
            return build(node.body)
        if isinstance(node, ast.BinOp):
            left, right = build(node.left), build(node.right)
            op = node.op
            if isinstance(op, ast.Add):
                return left + right
            if isinstance(op, ast.Sub):
                return left - right
            if isinstance(op, ast.Mult):
                return left * right
            if isinstance(op, ast.Div):
                return left / right
            if isinstance(op, ast.Mod):
                return left % right
            if isinstance(op, ast.Pow):
                return left ** right
            raise DeriveError("Unsupported operator.")
        if isinstance(node, ast.UnaryOp):
            val = build(node.operand)
            if isinstance(node.op, ast.USub):
                return -val
            if isinstance(node.op, ast.UAdd):
                return val
            raise DeriveError("Unsupported unary operator.")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in funcs:
                raise DeriveError("Unknown function.")
            arity, fn = funcs[node.func.id]
            if len(node.args) != arity or node.keywords:
                raise DeriveError(f"{node.func.id}() takes {arity} argument(s).")
            return fn(*[build(a) for a in node.args])
        if isinstance(node, ast.Name):
            if node.id in mapping:
                return pl.col(mapping[node.id])
            raise DeriveError(
                f"Unknown name {node.id!r} — reference columns in [brackets]."
            )
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise DeriveError("Only numeric constants are allowed.")
            return pl.lit(node.value)
        raise DeriveError("Unsupported expression.")

    return build(tree)


def apply(df, derivations):
    """Return ``df`` with each derivation added as a column.

    Applied in order so a derivation may build on an earlier one. Any that no
    longer compiles or evaluates against this frame (e.g. a referenced column
    isn't in this build) is skipped rather than raising — add-time validation
    is where problems are reported.
    """
    out = df
    for d in derivations or []:
        try:
            expr = compile_expr(d["expr"], out.columns)
            out = out.with_columns(expr.alias(d["name"]))
        except Exception:  # noqa: BLE001 — skip a bad derivation, keep the rest
            continue
    return out
