"""
Foundational recipe actions.

Enough to prove the engine end-to-end across both phases and the identity guard:

* :class:`FillColumn`    — derivation; broadcast a scalar to a new column
  (e.g. one ethanol temperature for every part). Carries an optional unit.
* :class:`RenameColumn`  — derivation; rename a column, optionally re-tagging its
  unit. Refused on the key column unless forced.
* :class:`DeleteColumn`  — derivation; drop a column. Refused on the key column
  unless forced (the part_id-guard case from the design).
* :class:`OverrideCell`  — override; correct one input cell, addressed by key
  value (not row index). Refused on the key column unless forced.

The richer actions (formula DSL, horizontal AVG/STD/ERR/SUM, calculate_density,
round/sig-figs, sort as a view setting) layer on top of this same protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import polars as pl

from ohpal.samples.analysis import (
    STATS,
    VALUE_STATS,
    canonical_stat,
    find_reading_columns,
    horizontal_stat,
    stat_suffix,
)
from ohpal.samples.formula import compile_formula, parse_formula
from ohpal.samples.recipe import BaseAction, Phase, RecipeError, register_action
from polars.exceptions import PolarsError

__all__ = [
    "FillColumn",
    "RenameColumn",
    "DeleteColumn",
    "OverrideCell",
    "FormulaColumn",
    "AggregateColumns",
]

# JSON-serialisable scalar cell values.
Scalar = float | int | str | bool | None


@register_action
@dataclass(frozen=True, kw_only=True)
class FillColumn(BaseAction):
    """Broadcast a constant ``value`` to every row of ``column`` (new or overwritten)."""

    kind: ClassVar[str] = "fill_column"
    phase: ClassVar[Phase] = Phase.DERIVATION

    column: str
    value: Scalar
    unit: str | None = None

    def _apply(self, frame: pl.DataFrame, *, key_column: str) -> pl.DataFrame:
        return frame.with_columns(pl.lit(self.value).alias(self.column))

    def units(self) -> dict[str, str]:
        return {self.column: self.unit} if self.unit else {}

    def label(self) -> str:
        u = f" {self.unit}" if self.unit else ""
        return f"Fill {self.column!r} = {self.value}{u}"


@register_action
@dataclass(frozen=True, kw_only=True)
class RenameColumn(BaseAction):
    """Rename ``old`` to ``new``, optionally attaching a unit to the result."""

    kind: ClassVar[str] = "rename_column"
    phase: ClassVar[Phase] = Phase.DERIVATION

    old: str
    new: str
    unit: str | None = None

    def _apply(self, frame: pl.DataFrame, *, key_column: str) -> pl.DataFrame:
        if self.old not in frame.columns:
            raise RecipeError(f"cannot rename: column {self.old!r} not found")
        if self.new in frame.columns and self.new != self.old:
            raise RecipeError(f"cannot rename to {self.new!r}: column already exists")
        return frame.rename({self.old: self.new})

    def units(self) -> dict[str, str]:
        return {self.new: self.unit} if self.unit else {}

    def label(self) -> str:
        return f"Rename {self.old!r} -> {self.new!r}"


@register_action
@dataclass(frozen=True, kw_only=True)
class DeleteColumn(BaseAction):
    """Drop ``column``. Blocked on the key column unless ``allow_identity_change``."""

    kind: ClassVar[str] = "delete_column"
    phase: ClassVar[Phase] = Phase.DERIVATION

    column: str

    def _apply(self, frame: pl.DataFrame, *, key_column: str) -> pl.DataFrame:
        if self.column not in frame.columns:
            raise RecipeError(f"cannot delete: column {self.column!r} not found")
        return frame.drop(self.column)

    def label(self) -> str:
        return f"Delete {self.column!r}"


@register_action
@dataclass(frozen=True, kw_only=True)
class OverrideCell(BaseAction):
    """Correct one input cell: set ``column`` to ``value`` for the row whose key
    equals ``key_value``. Addressed by key, so it survives sorting/downselection.
    """

    kind: ClassVar[str] = "override_cell"
    phase: ClassVar[Phase] = Phase.OVERRIDE

    key_value: str
    column: str
    value: Scalar

    def _apply(self, frame: pl.DataFrame, *, key_column: str) -> pl.DataFrame:
        if self.column not in frame.columns:
            raise RecipeError(f"cannot override: column {self.column!r} not found")
        if key_column not in frame.columns:
            raise RecipeError(f"cannot override: key column {key_column!r} not found")
        if frame.filter(pl.col(key_column) == self.key_value).height == 0:
            raise RecipeError(
                f"cannot override: no row with {key_column}={self.key_value!r} "
                f"(downselected or mistyped?)"
            )

        lit = pl.lit(self.value)
        if self.value is not None:
            lit = lit.cast(frame[self.column].dtype)
        else:
            lit = lit.cast(frame[self.column].dtype)

        return frame.with_columns(
            pl.when(pl.col(key_column) == self.key_value)
            .then(lit)
            .otherwise(pl.col(self.column))
            .alias(self.column)
        )

    def label(self) -> str:
        return f"Set {self.column!r}@{self.key_value} = {self.value}"


@register_action
@dataclass(frozen=True, kw_only=True)
class FormulaColumn(BaseAction):
    """Compute ``out`` from a safe column formula (see :mod:`ohpal.samples.formula`).

    ``([mass in air] - [mass in ethanol]) / [mass in air] * [rho_ethanol]``.
    New column by default; set ``overwrite=True`` to replace an existing one.
    The output unit can't be inferred from arithmetic, so it's declared.
    """

    kind: ClassVar[str] = "formula"
    phase: ClassVar[Phase] = Phase.DERIVATION

    out: str
    formula: str
    unit: str | None = None
    overwrite: bool = False

    def __post_init__(self) -> None:
        # Fail fast on syntax/security errors at construction (app type-time),
        # before any data is involved.
        parse_formula(self.formula)

    def _apply(self, frame: pl.DataFrame, *, key_column: str) -> pl.DataFrame:
        if self.out in frame.columns and not self.overwrite:
            raise RecipeError(
                f"column {self.out!r} already exists; pass overwrite=True to replace"
            )
        parsed = parse_formula(self.formula)
        expr = compile_formula(parsed, frame.columns)  # raises on unknown column
        try:
            return frame.with_columns(expr.alias(self.out))
        except PolarsError as e:
            raise RecipeError(f"formula {self.formula!r} failed: {e}") from e

    def units(self) -> dict[str, str]:
        return {self.out: self.unit} if self.unit else {}

    def label(self) -> str:
        return f"{self.out} = {self.formula}"


@register_action
@dataclass(frozen=True, kw_only=True)
class AggregateColumns(BaseAction):
    """Horizontal (per-part) reduction over a set of columns into new columns.

    The schema-tolerant sibling of the formula DSL's explicit reductions: select
    columns by numbered ``prefix`` (``Density (1)``, ``Density 2`` …) so the same
    recipe replays on sheets with three or six readings, or give an explicit
    ``columns`` list. Produces one output per requested stat, named
    ``{out_prefix}_{suffix}`` (e.g. ``density_avg``, ``density_sd``,
    ``density_sem``, ``density_n``), skipping nulls like ``summarize_readings``.

    Value stats (avg/sd/sem/sum/min/max/median) inherit the declared input
    ``unit``; ``n`` is a dimensionless count.
    """

    kind: ClassVar[str] = "aggregate_columns"
    phase: ClassVar[Phase] = Phase.DERIVATION

    out_prefix: str
    stats: tuple[str, ...]
    prefix: str | None = None
    columns: tuple[str, ...] | None = None
    unit: str | None = None
    ddof: int = 1
    overwrite: bool = False

    def __post_init__(self) -> None:
        if (self.prefix is None) == (self.columns is None):
            raise RecipeError("provide exactly one of prefix= or columns=")
        if not self.stats:
            raise RecipeError("stats must be non-empty")
        for s in self.stats:
            canonical_stat(s)  # validates; raises on unknown

    def _select(self, frame: pl.DataFrame) -> list[str]:
        if self.prefix is not None:
            cols = find_reading_columns(frame, self.prefix)
            if not cols:
                raise RecipeError(
                    f"no columns match prefix {self.prefix!r} on this sheet"
                )
            return cols
        missing = [c for c in self.columns if c not in frame.columns]
        if missing:
            raise RecipeError(f"columns not found: {missing}")
        return list(self.columns)

    def _apply(self, frame: pl.DataFrame, *, key_column: str) -> pl.DataFrame:
        cols = self._select(frame)
        exprs = [pl.col(c) for c in cols]

        outputs = {}
        for stat in self.stats:
            name = f"{self.out_prefix}_{stat_suffix(stat)}"
            if name in frame.columns and not self.overwrite:
                raise RecipeError(
                    f"column {name!r} already exists; pass overwrite=True to replace"
                )
            outputs[name] = horizontal_stat(exprs, stat, ddof=self.ddof)
        return frame.with_columns(**outputs)

    def units(self) -> dict[str, str]:
        if not self.unit:
            return {}
        return {
            f"{self.out_prefix}_{stat_suffix(s)}": self.unit
            for s in self.stats
            if canonical_stat(s) in VALUE_STATS
        }

    def label(self) -> str:
        sel = f"prefix {self.prefix!r}" if self.prefix is not None else f"{len(self.columns)} cols"
        return f"Aggregate {sel} -> {self.out_prefix}_[{','.join(self.stats)}]"
