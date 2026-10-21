"""``ohpal.samples`` — characterisation workbooks into tidy, analysable frames.

Tier 1 (here): read a hand-written sheet and crunch it, no build file or
``part_id`` required. Tier 2 (the part-attribute provider that adds identity and
contributes columns to the part matrix) builds on this and lands later.
"""

from __future__ import annotations

from ohpal.samples.analysis import (
    NoReadingColumns,
    UnknownStat,
    find_reading_columns,
    horizontal_stat,
    summarize_readings,
)
from ohpal.samples.io import TableReadError, read_table
from ohpal.samples.recipe import (
    Action,
    IdentityGuardError,
    Phase,
    Recipe,
    RecipeError,
    action_from_dict,
    register_action,
)
from ohpal.samples.actions import (
    AggregateColumns,
    DeleteColumn,
    FillColumn,
    FormulaColumn,
    OverrideCell,
    RenameColumn,
)
from ohpal.samples.formula import (
    FormulaColumnError,
    FormulaError,
    FormulaSecurityError,
    FormulaSyntaxError,
    compile_formula,
    parse_formula,
)
from ohpal.samples.template import (
    build_template_frame,
    create_template,
    create_template_from_dhxml,
)
from ohpal.samples.writer import WriteError, write_csv, write_table, write_xlsx

__all__ = [
    # io / analysis
    "read_table",
    "TableReadError",
    "summarize_readings",
    "find_reading_columns",
    "horizontal_stat",
    "NoReadingColumns",
    "UnknownStat",
    # recipe engine
    "Recipe",
    "Action",
    "Phase",
    "RecipeError",
    "IdentityGuardError",
    "register_action",
    "action_from_dict",
    # actions
    "FillColumn",
    "RenameColumn",
    "DeleteColumn",
    "OverrideCell",
    "FormulaColumn",
    "AggregateColumns",
    # formula DSL
    "parse_formula",
    "compile_formula",
    "FormulaError",
    "FormulaSyntaxError",
    "FormulaSecurityError",
    "FormulaColumnError",
    # template generation + writing
    "build_template_frame",
    "create_template",
    "create_template_from_dhxml",
    "write_table",
    "write_xlsx",
    "write_csv",
    "WriteError",
]
