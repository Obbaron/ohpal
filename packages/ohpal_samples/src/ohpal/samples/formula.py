"""
A safe column-formula DSL.

Formulas are ordinary arithmetic over column references and a whitelist of
functions::

    ([mass in air] - [mass in ethanol]) / [mass in air] * [rho_ethanol]
    mean([Density 1], [Density 2], [Density 3])
    round(([x] + 3) * 2, 2)

Columns are written in ``[...]`` so real headers (``[Density AVG (g/cm^3)]``,
``[σ]``) just work and never collide with function names. Functions are bare
identifiers; numbers are literals.

Design — two boundaries, and never ``eval``
-------------------------------------------
A formula's life cycle is parse -> validate -> compile -> polars expression:

1. **parse** — ``[...]`` spans are swapped for safe placeholders, then Python's
   own ``ast`` parses the rest (correct precedence/associativity for free).
2. **validate** (:func:`parse_formula`) — a strict default-deny walk of the AST.
   This is the *security boundary*; it needs no data, so an app can validate a
   formula the moment it is typed. Anything not explicitly allowed is rejected,
   so a new AST node in a future Python is denied by default.
3. **compile** (:func:`compile_formula`) — translate the validated tree into a
   ``pl.Expr``, binding column references. This is the *schema boundary*: it is
   where "column not found" is raised, because it needs to know what columns
   exist.
4. polars evaluates, vectorised — so null propagation and dtype promotion are
   polars' native behaviour, not code we reimplement.

The formula string is the canonical serialised form; there is nothing else to
persist or version.

Null / non-finite policy
------------------------
Arithmetic propagates nulls. Reductions skip nulls (empty mean -> null, empty
sum -> 0). The output is cast to Float64 and any non-finite value (NaN from
``0/0``, inf from ``x/0``) is mapped to null, so the frame has exactly one
notion of "missing".
"""

from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass

import polars as pl
from polars.exceptions import PolarsError

__all__ = [
    "parse_formula",
    "compile_formula",
    "ParsedFormula",
    "FormulaError",
    "FormulaSyntaxError",
    "FormulaSecurityError",
    "FormulaColumnError",
]

_PLACEHOLDER = "_ohpalcol_"
_BRACKET = re.compile(r"\[([^\[\]]*)\]")

# Bare-identifier constants.
_CONSTANTS = {"pi": math.pi, "e": math.e}

# Unary, row-wise, null-propagating.
_UNARY = {"sqrt", "exp", "log", "log10", "abs"}
# Variadic, horizontal, null-skipping.
_REDUCE = {"mean", "avg", "sum", "min", "max", "std", "median", "sem"}
_FUNCS = _UNARY | _REDUCE | {"round"}

_BIN_OPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod)
_UNARY_OPS = (ast.UAdd, ast.USub)


class FormulaError(ValueError):
    """Base for formula problems."""


class FormulaSyntaxError(FormulaError):
    """The formula is not well-formed."""


class FormulaSecurityError(FormulaError):
    """The formula uses a construct outside the allowed grammar."""


class FormulaColumnError(FormulaError):
    """The formula references a column not present in the frame."""


@dataclass(frozen=True)
class ParsedFormula:
    """A validated formula: safe to compile, with its column references known."""

    source: str
    tree: ast.Expression
    _mapping: dict[str, str]  # placeholder -> real column name

    @property
    def columns(self) -> set[str]:
        """Column names the formula references (known without any data)."""
        return set(self._mapping.values())


def _preprocess(formula: str) -> tuple[str, dict[str, str]]:
    """Replace ``[col]`` spans with safe placeholders; return cleaned text + map.

    Bracket contents are treated as raw column-name strings and never parsed as
    code, so nothing executable can hide inside ``[...]``.
    """
    if _PLACEHOLDER in _BRACKET.sub(" ", formula):
        raise FormulaSecurityError(f"{_PLACEHOLDER!r} is a reserved token")

    mapping: dict[str, str] = {}

    def repl(m: re.Match) -> str:
        name = m.group(1).strip()
        if not name:
            raise FormulaSyntaxError("empty [] column reference")
        placeholder = f"{_PLACEHOLDER}{len(mapping)}"
        mapping[placeholder] = name
        return placeholder

    return _BRACKET.sub(repl, formula), mapping


def _validate(node: ast.AST, allowed_names: set[str]) -> None:
    """Default-deny walk: reject any construct not explicitly permitted."""
    if isinstance(node, ast.BinOp):
        if not isinstance(node.op, _BIN_OPS):
            raise FormulaSecurityError(f"operator {type(node.op).__name__} not allowed")
        _validate(node.left, allowed_names)
        _validate(node.right, allowed_names)

    elif isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, _UNARY_OPS):
            raise FormulaSecurityError(f"unary {type(node.op).__name__} not allowed")
        _validate(node.operand, allowed_names)

    elif isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise FormulaSecurityError(f"only numeric constants allowed, got {node.value!r}")

    elif isinstance(node, ast.Call):
        if node.keywords or any(isinstance(a, ast.Starred) for a in node.args):
            raise FormulaSecurityError("keyword and *args not allowed in calls")
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
            name = getattr(node.func, "id", type(node.func).__name__)
            raise FormulaSecurityError(f"unknown function {name!r}")
        for a in node.args:
            _validate(a, allowed_names)

    elif isinstance(node, ast.Name):
        if node.id not in allowed_names:
            hint = "" if node.id in _FUNCS else f"; reference a column as [{node.id}]"
            raise FormulaSecurityError(f"unknown name {node.id!r}{hint}")

    else:
        raise FormulaSecurityError(f"{type(node).__name__} is not allowed")


def parse_formula(formula: str) -> ParsedFormula:
    """Parse and security-validate a formula. No data needed (app type-time)."""
    cleaned, mapping = _preprocess(formula)
    try:
        tree = ast.parse(cleaned, mode="eval")
    except SyntaxError as e:
        raise FormulaSyntaxError(f"invalid formula: {e.msg}") from e

    allowed = set(mapping) | set(_CONSTANTS)
    _validate(tree.body, allowed)
    return ParsedFormula(source=formula, tree=tree, _mapping=mapping)


# ---- compile: validated AST -> pl.Expr (schema boundary) ------------------

def _reduce(args: list[pl.Expr], kind: str) -> pl.Expr:
    # One definition of horizontal reductions, shared with summarize_readings
    # and the aggregate action.
    from ohpal.samples.analysis import horizontal_stat

    return horizontal_stat(args, kind)


def _call_expr(node: ast.Call, mapping: dict[str, str]) -> pl.Expr:
    name = node.func.id  # validated to be a known function
    args = [_node_expr(a, mapping) for a in node.args]

    if name in _UNARY:
        if len(args) != 1:
            raise FormulaError(f"{name}() takes exactly one argument")
        x = args[0]
        return {
            "sqrt": x.sqrt(), "exp": x.exp(), "log": x.log(),
            "log10": x.log10(), "abs": x.abs(),
        }[name]

    if name == "round":
        if not 1 <= len(node.args) <= 2:
            raise FormulaError("round(x[, n]) takes one or two arguments")
        n = 0
        if len(node.args) == 2:
            a1 = node.args[1]
            if not (isinstance(a1, ast.Constant) and isinstance(a1.value, int)
                    and not isinstance(a1.value, bool)):
                raise FormulaError("round(x, n): n must be an integer literal")
            n = a1.value
        return args[0].round(n)

    # reductions
    if not args:
        raise FormulaError(f"{name}() needs at least one argument")
    return _reduce(args, name)


def _node_expr(node: ast.AST, mapping: dict[str, str]) -> pl.Expr:
    if isinstance(node, ast.BinOp):
        left, right = _node_expr(node.left, mapping), _node_expr(node.right, mapping)
        op = node.op
        if isinstance(op, ast.Add):
            return left + right
        if isinstance(op, ast.Sub):
            return left - right
        if isinstance(op, ast.Mult):
            return left * right
        if isinstance(op, ast.Div):
            return left / right
        if isinstance(op, ast.Pow):
            return left ** right
        return left % right  # Mod (only remaining allowed op)

    if isinstance(node, ast.UnaryOp):
        operand = _node_expr(node.operand, mapping)
        return -operand if isinstance(node.op, ast.USub) else operand

    if isinstance(node, ast.Constant):
        return pl.lit(node.value)

    if isinstance(node, ast.Call):
        return _call_expr(node, mapping)

    if isinstance(node, ast.Name):
        if node.id in mapping:
            return pl.col(mapping[node.id])
        return pl.lit(_CONSTANTS[node.id])

    raise FormulaSecurityError(f"{type(node).__name__} is not allowed")  # pragma: no cover


def compile_formula(parsed: ParsedFormula, available: object) -> pl.Expr:
    """Translate a validated formula into a ``pl.Expr``.

    ``available`` is the collection of column names present in the target frame;
    a reference to any absent column raises :class:`FormulaColumnError`. The
    result is Float64 with non-finite values mapped to null.
    """
    available = set(available)
    missing = parsed.columns - available
    if missing:
        raise FormulaColumnError(
            f"formula references unknown column(s) {sorted(missing)}; "
            f"available: {sorted(available)}"
        )

    expr = _node_expr(parsed.tree.body, parsed._mapping).cast(pl.Float64, strict=False)
    # Single notion of missing: NaN (0/0) and inf (x/0) both become null.
    return pl.when(expr.is_finite()).then(expr).otherwise(None)


def evaluate(formula: str, frame: pl.DataFrame) -> pl.Series:
    """Convenience: parse + compile + evaluate against a frame (one Series out)."""
    parsed = parse_formula(formula)
    expr = compile_formula(parsed, frame.columns)
    try:
        return frame.select(expr.alias("__result__"))["__result__"]
    except PolarsError as e:
        raise FormulaError(f"evaluating {formula!r}: {e}") from e
