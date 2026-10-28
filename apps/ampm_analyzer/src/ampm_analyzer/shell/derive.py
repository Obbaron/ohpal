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
# Inline per-aggregate grouping: `mean([mp]) by [part, side]`. Rewritten to a
# method call `.__over__('part', 'side')` so it binds to the preceding aggregate.
_BY_RE = re.compile(r"\bby\s*\[([^\[\]]+)\]")
# Masked value: `[x] where [cond]` -> __mask__([x], [cond]). The negative
# lookahead keeps the where(cond, a, b) ternary (where immediately before "(")
# separate from this infix mask.
_WHERE_RE = re.compile(r"\bwhere\b(?!\s*\()")

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
    funcs = {name: (1, fn) for name, fn in {**agg, **elem}.items()}
    # Multi-arg: where(cond, a, b) -> a where cond is true, else b.
    import polars as pl

    funcs["where"] = (3, lambda c, a, b: pl.when(c).then(a).otherwise(b))
    return funcs


def _apply_where(text: str) -> str:
    """Rewrite each infix `VALUE where COND` to `__mask__(VALUE, COND)`.

    VALUE is the bracketed/parenthesised primary just before `where`; COND runs
    from after `where` to the enclosing `)`/`]`/`,` (bracket-depth aware). Applied
    left-to-right so nested masks resolve on later passes.
    """
    for _ in range(100):  # bounded; each pass removes one `where`
        m = _WHERE_RE.search(text)
        if not m:
            return text
        i = m.start() - 1
        while i >= 0 and text[i] == " ":
            i -= 1
        if i < 0:
            raise DeriveError("'where' needs a value on its left.")
        if text[i] in "])":
            close, openc = text[i], ("[" if text[i] == "]" else "(")
            depth, j = 0, i
            while j >= 0:
                if text[j] == close:
                    depth += 1
                elif text[j] == openc:
                    depth -= 1
                    if depth == 0:
                        break
                j -= 1
            if j < 0:
                raise DeriveError("Unbalanced brackets before 'where'.")
            left_start = j
        else:
            j = i
            while j >= 0 and (text[j].isalnum() or text[j] in "._"):
                j -= 1
            left_start = j + 1
        left = text[left_start:i + 1].strip()

        k = m.end()
        while k < len(text) and text[k] == " ":
            k += 1
        right_start, depth = k, 0
        while k < len(text):
            c = text[k]
            if c in "([":
                depth += 1
            elif c in ")]":
                if depth == 0:
                    break
                depth -= 1
            elif c == "," and depth == 0:
                break
            k += 1
        right = text[right_start:k].strip()
        if not left:
            raise DeriveError("'where' needs a value on its left.")
        if not right:
            raise DeriveError("'where' needs a condition on its right.")
        text = text[:left_start] + f"__mask__({left}, {right})" + text[k:]
    raise DeriveError("Too many 'where' clauses.")


# -- parsing ------------------------------------------------------------
def _parse(text: str, columns, what: str):
    """Bracket-substitute, parse to an AST, return (tree, mapping)."""
    text = (text or "").strip()
    if not text:
        raise DeriveError(f"{what} is empty.")

    known = set(columns)

    # 0. Masked values `… where …` -> __mask__(value, cond) (before anything).
    text = _apply_where(text)

    # 1. Inline grouping `… by [a, b]` -> `.__over__('a', 'b')` (validate names).
    def _by_sub(m: re.Match) -> str:
        cols = [c.strip() for c in m.group(1).split(",")]
        for c in cols:
            if not c:
                raise DeriveError("Empty column name in a 'by [...]' group.")
            if c not in known:
                raise DeriveError(f"Unknown column: {c!r}")
        return ".__over__(" + ", ".join(repr(c) for c in cols) + ")"

    text = _BY_RE.sub(_by_sub, text)

    # 2. Value columns `[Name]` -> placeholder identifiers.
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


_COMPARE_OPS = {
    ast.Lt: lambda a, b: a < b,
    ast.Gt: lambda a, b: a > b,
    ast.LtE: lambda a, b: a <= b,
    ast.GtE: lambda a, b: a >= b,
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
}


def _contains_agg(node) -> bool:
    """True if the AST subtree calls any aggregate function."""
    for n in ast.walk(node):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id in _AGGREGATE):
            return True
    return False


def _build_value(node, mapping, funcs, ctx=None):
    """Compile an AST node to a Polars expression.

    Handles arithmetic and functions *and* comparisons (< <= > >= == !=) with
    boolean ``and`` / ``or`` / ``not`` — so a derived column can be a number or a
    condition (a boolean column). Comparisons chain: ``0 < [x] < 10``.

    ``ctx`` (a dict with "stages" and "n") enables nested aggregation: when an
    aggregate's argument itself contains an aggregate, the inner part is
    materialised to a temp column first (its ``.over`` broadcast to rows), and
    the outer aggregate reduces that column. Inner materialisations are appended
    before outer ones, so the stages come out in dependency order.
    """
    import polars as pl

    if isinstance(node, ast.Expression):
        return _build_value(node.body, mapping, funcs, ctx)
    if isinstance(node, ast.BoolOp):
        parts = [_build_value(v, mapping, funcs, ctx) for v in node.values]
        out = parts[0]
        for p in parts[1:]:
            out = (out & p) if isinstance(node.op, ast.And) else (out | p)
        return out
    if isinstance(node, ast.Compare):
        operands = [node.left, *node.comparators]
        terms = []
        for i, op in enumerate(node.ops):
            builder = _COMPARE_OPS.get(type(op))
            if builder is None:
                raise DeriveError("Unsupported comparison.")
            terms.append(builder(_build_value(operands[i], mapping, funcs, ctx),
                                 _build_value(operands[i + 1], mapping, funcs, ctx)))
        out = terms[0]
        for t in terms[1:]:
            out = out & t
        return out
    if isinstance(node, ast.BinOp):
        left = _build_value(node.left, mapping, funcs, ctx)
        right = _build_value(node.right, mapping, funcs, ctx)
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
        if isinstance(node.op, ast.Not):
            return ~_build_value(node.operand, mapping, funcs, ctx)
        if isinstance(node.op, ast.USub):
            return -_build_value(node.operand, mapping, funcs, ctx)
        if isinstance(node.op, ast.UAdd):
            return _build_value(node.operand, mapping, funcs, ctx)
        raise DeriveError("Unsupported unary operator.")
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Attribute) and node.func.attr == "__over__":
            # `expr by [a, b]` -> expr.over([a, b]) — per-aggregate grouping.
            base = _build_value(node.func.value, mapping, funcs, ctx)
            cols = [a.value for a in node.args
                    if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            if not cols:
                raise DeriveError("'by' needs at least one column.")
            return base.over(cols)
        if isinstance(node.func, ast.Name) and node.func.id == "__mask__":
            # `[x] where [cond]` -> keep x where cond, else null (so a reducer
            # like mean()/std() aggregates only the masked rows).
            val = _build_value(node.args[0], mapping, funcs, ctx)
            cond = _build_value(node.args[1], mapping, funcs, ctx)
            return pl.when(cond).then(val).otherwise(None)
        if not isinstance(node.func, ast.Name) or node.func.id not in funcs:
            raise DeriveError("Unknown function.")
        fname = node.func.id
        arity, fn = funcs[fname]
        if len(node.args) != arity or node.keywords:
            raise DeriveError(f"{fname}() takes {arity} argument(s).")
        # Nested aggregation: an aggregate over an argument that itself
        # aggregates. Materialise the inner argument first so this reduction
        # operates on a plain column (Polars can't nest .over() correctly).
        if (ctx is not None and fname in _AGGREGATE
                and _contains_agg(node.args[0])):
            inner = _build_value(node.args[0], mapping, funcs, ctx)
            tmp = f"__agg{ctx['n']}"
            ctx["n"] += 1
            ctx["stages"].append((tmp, inner))
            return fn(pl.col(tmp))
        return fn(*[_build_value(a, mapping, funcs, ctx) for a in node.args])
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


def _build_predicate(node, mapping, funcs):
    """Compile a condition — like _build_value, but the top level must be a
    boolean (a comparison / and / or / not), as a Group-label rule requires."""
    body = node.body if isinstance(node, ast.Expression) else node
    is_bool = isinstance(body, (ast.Compare, ast.BoolOp)) or (
        isinstance(body, ast.UnaryOp) and isinstance(body.op, ast.Not)
    )
    if not is_bool:
        raise DeriveError(
            "Condition must be a comparison (use <, >, ==, and, or)."
        )
    return _build_value(node, mapping, funcs)


# -- public compile -----------------------------------------------------
def _compile_formula(text: str, columns):
    """Compile a formula to (stages, final_expr).

    ``stages`` are (temp_name, expr) materialisations to apply in order (for
    nested aggregation); empty for ordinary formulas. ``final_expr`` is the
    column expression, which may reference the staged temp columns.
    """
    tree, mapping = _parse(text, columns, "Expression")
    ctx = {"stages": [], "n": 0}
    expr = _build_value(tree, mapping, _functions(), ctx)
    return ctx["stages"], expr


def compile_expr(text: str, columns) -> Any:
    """Compile a formula (numeric or condition) to a Polars expression."""
    return _compile_formula(text, columns)[1]


def compile_predicate(text: str, columns) -> Any:
    """Compile a boolean condition to a Polars expression. Raises DeriveError."""
    tree, mapping = _parse(text, columns, "Condition")
    return _build_predicate(tree, mapping, _functions())


# -- application --------------------------------------------------------
def _apply_formula(out, d):
    """Add a formula column to ``out``, running any staged materialisations
    (for nested aggregation) first and cleaning up the temp columns after."""
    text = d["expr"]
    stages, expr = _compile_formula(text, out.columns)
    group = d.get("group")
    # The dropdown wraps the whole formula; skip it when the formula already
    # scopes grouping per-aggregate with inline `by [...]`.
    if group and group in out.columns and not _BY_RE.search(text or ""):
        expr = expr.over(group)
    for tmp, stage_expr in stages:
        out = out.with_columns(stage_expr.alias(tmp))
    out = out.with_columns(expr.alias(d["name"]))
    if stages:
        out = out.drop([tmp for tmp, _ in stages])
    return out


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
            if d.get("kind", "formula") == "label":
                out = out.with_columns(_label_expr(d, out.columns).alias(d["name"]))
            else:
                out = _apply_formula(out, d)
        except Exception:  # noqa: BLE001 — skip a bad derivation, keep the rest
            continue
    return out
