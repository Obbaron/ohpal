"""Derived columns.

Two kinds, both re-applied to every query result (so they survive layer
changes) and both referencing columns by name in square brackets, e.g.
``[MeltVIEW melt pool (mean)]``:

* **formula** — a numeric expression. Mixes *element-wise* functions (per row:
  abs, sqrt, …) and *aggregate* functions (reduce a column: mean, std, …). An
  aggregate on its own is the whole-frame value broadcast to every row; with a
  ``group`` column it is evaluated within each group and mapped back to its rows
  (Polars ``.over``), so ``cov([signal])`` grouped by ``part`` gives each row
  its part's CoV.

* **label** — ordered if/elif/else rules. Each rule is a boolean condition
  (comparisons with ``and`` / ``or`` / ``not``) and a text label; the first
  matching rule wins, and rows matching none get the default label. Good for
  tagging regions, e.g. ``[Demand X] > 30 and [Demand Y] < -21`` → "group1".

Everything is parsed to an AST and compiled to a Polars expression — never
``eval``-ed. Derivations apply in order, so a later one may reference an earlier.
"""

from __future__ import annotations

import ast
import re
from typing import Any

_TOKEN_RE = re.compile(r"\[([^\[\]]+)\]")

# Element-wise (per-row) functions.
_ELEMENTWISE = ("abs", "sqrt", "log", "log10", "exp", "sin", "cos")
# Aggregate (reduction) functions — one value per group (or whole frame).
_AGGREGATE = (
    "mean", "std", "var", "median", "sum",
    "min", "max", "count", "n_unique", "first", "last", "cov",
)


class DeriveError(ValueError):
    """A formula/condition that can't be compiled (bad syntax, unknown column…)."""


def _functions() -> dict[str, tuple[int, Any]]:
    agg = {
        "mean": lambda a: a.mean(),
        "std": lambda a: a.std(),
        "var": lambda a: a.var(),
        "median": lambda a: a.median(),
        "sum": lambda a: a.sum(),
        "min": lambda a: a.min(),
        "max": lambda a: a.max(),
        "count": lambda a: a.count(),
        "n_unique": lambda a: a.n_unique(),
        "first": lambda a: a.first(),
        "last": lambda a: a.last(),
        "cov": lambda a: a.std() / a.mean(),  # coefficient of variation
    }
    elem = {
        "abs": lambda a: a.abs(),
        "sqrt": lambda a: a.sqrt(),
        "log": lambda a: a.log(),
        "log10": lambda a: a.log10(),
        "exp": lambda a: a.exp(),
        "sin": lambda a: a.sin(),
        "cos": lambda a: a.cos(),
    }
    return {name: (1, fn) for name, fn in {**agg, **elem}.items()}


# -- parsing ------------------------------------------------------------
def _parse(text: str, columns, what: str):
    """Bracket-substitute, parse to an AST, return (tree, mapping)."""
    text = (text or "").strip()
    if not text:
        raise DeriveError(f"{what} is empty.")

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
        raise DeriveError(f"Unbalanced '[' / ']' in {what.lower()}.")

    try:
        tree = ast.parse(substituted, mode="eval")
    except SyntaxError as exc:
        raise DeriveError(f"Could not parse {what.lower()}: {exc.msg}") from exc
    return tree, mapping


def _build_value(node, mapping, funcs):
    """Compile a numeric/value AST node to a Polars expression."""
    import polars as pl

    if isinstance(node, ast.Expression):
        return _build_value(node.body, mapping, funcs)
    if isinstance(node, ast.BinOp):
        left = _build_value(node.left, mapping, funcs)
        right = _build_value(node.right, mapping, funcs)
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
        if isinstance(node.op, ast.USub):
            return -_build_value(node.operand, mapping, funcs)
        if isinstance(node.op, ast.UAdd):
            return _build_value(node.operand, mapping, funcs)
        raise DeriveError("Unsupported unary operator.")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in funcs:
            raise DeriveError("Unknown function.")
        arity, fn = funcs[node.func.id]
        if len(node.args) != arity or node.keywords:
            raise DeriveError(f"{node.func.id}() takes {arity} argument(s).")
        return fn(*[_build_value(a, mapping, funcs) for a in node.args])
    if isinstance(node, ast.Name):
        if node.id in mapping:
            return pl.col(mapping[node.id])
        raise DeriveError(
            f"Unknown name {node.id!r} — reference columns in [brackets]."
        )
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            raise DeriveError("Booleans aren't allowed here.")
        if isinstance(node.value, (int, float, str)):
            return pl.lit(node.value)
        raise DeriveError("Only numbers and quoted text are allowed.")
    raise DeriveError("Unsupported expression.")


_COMPARE_OPS = {
    ast.Lt: lambda a, b: a < b,
    ast.Gt: lambda a, b: a > b,
    ast.LtE: lambda a, b: a <= b,
    ast.GtE: lambda a, b: a >= b,
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
}


def _build_predicate(node, mapping, funcs):
    """Compile a boolean-condition AST node to a Polars expression."""
    if isinstance(node, ast.Expression):
        return _build_predicate(node.body, mapping, funcs)
    if isinstance(node, ast.BoolOp):
        parts = [_build_predicate(v, mapping, funcs) for v in node.values]
        combined = parts[0]
        for p in parts[1:]:
            combined = (combined & p) if isinstance(node.op, ast.And) else (combined | p)
        return combined
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return ~_build_predicate(node.operand, mapping, funcs)
    if isinstance(node, ast.Compare):
        # Supports chaining: ``0 < [x] < 10`` -> (0 < x) & (x < 10).
        operands = [node.left, *node.comparators]
        terms = []
        for i, op in enumerate(node.ops):
            builder = _COMPARE_OPS.get(type(op))
            if builder is None:
                raise DeriveError("Unsupported comparison.")
            left = _build_value(operands[i], mapping, funcs)
            right = _build_value(operands[i + 1], mapping, funcs)
            terms.append(builder(left, right))
        combined = terms[0]
        for t in terms[1:]:
            combined = combined & t
        return combined
    raise DeriveError("Condition must be a comparison (use <, >, ==, and, or).")


# -- public compile -----------------------------------------------------
def compile_expr(text: str, columns) -> Any:
    """Compile a numeric formula to a Polars expression. Raises DeriveError."""
    tree, mapping = _parse(text, columns, "Expression")
    return _build_value(tree, mapping, _functions())


def compile_predicate(text: str, columns) -> Any:
    """Compile a boolean condition to a Polars expression. Raises DeriveError."""
    tree, mapping = _parse(text, columns, "Condition")
    return _build_predicate(tree, mapping, _functions())


# -- application --------------------------------------------------------
def _formula_expr(d, columns):
    expr = compile_expr(d["expr"], columns)
    group = d.get("group")
    if group and group in columns:
        expr = expr.over(group)  # per-group, mapped back to rows
    return expr


def _label_expr(d, columns):
    import polars as pl

    when = None
    for rule in d.get("rules", []):
        cond = compile_predicate(rule["cond"], columns)
        label = pl.lit(rule["label"])
        when = pl.when(cond).then(label) if when is None else when.when(cond).then(label)
    default = pl.lit(d.get("default", ""))
    return default if when is None else when.otherwise(default)


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
            kind = d.get("kind", "formula")
            if kind == "label":
                expr = _label_expr(d, out.columns)
            else:
                expr = _formula_expr(d, out.columns)
            out = out.with_columns(expr.alias(d["name"]))
        except Exception:  # noqa: BLE001 — skip a bad derivation, keep the rest
            continue
    return out
