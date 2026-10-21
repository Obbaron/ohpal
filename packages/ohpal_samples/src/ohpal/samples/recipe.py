"""
The recipe engine behind the "lite Excel editor".

Editing is modelled as an ordered, serialisable **recipe** of declarative
actions replayed on top of the raw ``read_table`` frame — not as in-place
mutation. That single choice buys provenance (the recipe *is* the record of how
every derived column was made), reproducibility (fix a source cell, replay,
everything downstream updates), and — because the recipe is the undo stack —
Ctrl+Z / Ctrl+Y for free.

Two ideas do the load-bearing work:

**Two phases, chronological history.** Actions are either *overrides*
(corrections to source input cells, addressed by key value — never row index)
or *derivations* (new/overwritten columns). Overrides always evaluate before
derivations, so a derived column sees corrected inputs. But the recipe is kept
as one *chronological* list, so undo pops the last action the user actually took
— history is chronological, evaluation is phased.

**Structural identity guard.** The recipe is built around a ``key_column`` (the
identity column — ``part_id`` in the provider role, or the sheet's anchor like
``Cube ID`` when editing standalone). After every action the engine asserts the
key column still exists with the same multiset of values; an action that would
delete, rename, or edit it is refused unless it explicitly carries
``allow_identity_change=True``. The guard lives in one place and no action can
forget it.

Evaluation is a pure replay (source + actions -> frame), so undo/redo and
save/reload compose. Per-step frame caching is a later drop-in and nothing here
forecloses it.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Protocol, runtime_checkable

import polars as pl

__all__ = [
    "Phase",
    "Action",
    "BaseAction",
    "Recipe",
    "RecipeError",
    "IdentityGuardError",
    "register_action",
    "action_from_dict",
]


class RecipeError(ValueError):
    """An action or recipe is invalid."""


class IdentityGuardError(RecipeError):
    """An action would alter the identity (key) column without being forced."""


class Phase(Enum):
    """Evaluation phase. Overrides always run before derivations."""

    OVERRIDE = "override"
    DERIVATION = "derivation"


@runtime_checkable
class Action(Protocol):
    """One declarative editing step.

    ``apply`` is pure — frame in, frame out — and receives the recipe's
    ``key_column`` so key-addressed actions (overrides) can find their row.
    ``kind`` is the stable tag used for (de)serialisation; ``phase`` fixes
    evaluation order; ``allow_identity_change`` opts the step out of the
    identity guard.
    """

    kind: ClassVar[str]
    phase: ClassVar[Phase]
    allow_identity_change: bool

    def apply(self, frame: pl.DataFrame, *, key_column: str) -> pl.DataFrame: ...

    def to_dict(self) -> dict[str, Any]: ...

    def label(self) -> str: ...

    def units(self) -> dict[str, str]: ...


_REGISTRY: dict[str, type["BaseAction"]] = {}


def register_action(cls: type["BaseAction"]) -> type["BaseAction"]:
    """Class decorator: make an action reconstructable via :func:`action_from_dict`."""
    if cls.kind in _REGISTRY:
        raise RecipeError(f"duplicate action kind {cls.kind!r}")
    _REGISTRY[cls.kind] = cls
    return cls


def action_from_dict(d: dict[str, Any]) -> "BaseAction":
    """Rebuild an action from its ``to_dict`` form."""
    kind = d.get("kind")
    if kind not in _REGISTRY:
        raise RecipeError(f"unknown action kind {kind!r}")
    return _REGISTRY[kind].from_dict(d)


@dataclass(frozen=True, kw_only=True)
class BaseAction:
    """Shared serialisation/label plumbing for concrete actions.

    Concrete actions subclass this, set ``kind``/``phase`` as ClassVars, add
    their parameters as keyword-only fields, and implement ``_apply``.
    """

    kind: ClassVar[str] = "base"
    phase: ClassVar[Phase] = Phase.DERIVATION

    # Opt-out of the identity guard. Only meaningful for actions that can touch
    # the key column, but carried uniformly so the engine treats it one way.
    allow_identity_change: bool = False

    # -- subclasses implement this --
    def _apply(self, frame: pl.DataFrame, *, key_column: str) -> pl.DataFrame:
        raise NotImplementedError

    def apply(self, frame: pl.DataFrame, *, key_column: str) -> pl.DataFrame:
        return self._apply(frame, key_column=key_column)

    def units(self) -> dict[str, str]:
        return {}

    def label(self) -> str:
        return self.kind

    def to_dict(self) -> dict[str, Any]:
        d = {f.name: getattr(self, f.name) for f in dataclasses.fields(self)}
        d["kind"] = self.kind
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BaseAction":
        params = {k: v for k, v in d.items() if k != "kind"}
        return cls(**params)


def _key_multiset(frame: pl.DataFrame, key: str) -> list | None:
    if key not in frame.columns:
        return None
    return sorted(frame[key].to_list(), key=lambda v: (v is None, v))


class Recipe:
    """An ordered, replayable editing session over one frame.

    Parameters
    ----------
    source
        The raw frame to edit (e.g. from ``read_table``). Never mutated.
    key_column
        The identity column the guard protects. Must exist in ``source``.
    """

    def __init__(self, source: pl.DataFrame, *, key_column: str = "part_id") -> None:
        if key_column not in source.columns:
            raise RecipeError(
                f"key_column {key_column!r} not in source columns {source.columns}"
            )
        self._source = source
        self._key = key_column
        self._actions: list[BaseAction] = []
        self._cursor = 0  # actions[:_cursor] are active; the rest is the redo tail

    # -- introspection ------------------------------------------------------

    @property
    def key_column(self) -> str:
        return self._key

    @property
    def actions(self) -> list[BaseAction]:
        """The currently active actions, in chronological order."""
        return list(self._actions[: self._cursor])

    def history(self) -> list[str]:
        """Human labels for the active actions (for an undo menu)."""
        return [a.label() for a in self.actions]

    def can_undo(self) -> bool:
        return self._cursor > 0

    def can_redo(self) -> bool:
        return self._cursor < len(self._actions)

    # -- editing ------------------------------------------------------------

    def do(self, action: BaseAction) -> "Recipe":
        """Append an action (discarding any redo tail) and validate it.

        Validation replays the recipe; if the new action is invalid (e.g. it
        trips the identity guard) it is rolled back and the error raised, so the
        recipe is always left in a computable state.
        """
        del self._actions[self._cursor :]  # drop redo tail
        self._actions.append(action)
        self._cursor += 1
        try:
            self.result()
        except Exception:
            self._cursor -= 1
            del self._actions[self._cursor :]
            raise
        return self

    def undo(self) -> "Recipe":
        if not self.can_undo():
            raise RecipeError("nothing to undo")
        self._cursor -= 1
        return self

    def redo(self) -> "Recipe":
        if not self.can_redo():
            raise RecipeError("nothing to redo")
        self._cursor += 1
        return self

    # -- evaluation ---------------------------------------------------------

    def result(self) -> pl.DataFrame:
        """Compute the edited frame: overrides first, then derivations."""
        active = self._actions[: self._cursor]
        overrides = [a for a in active if a.phase is Phase.OVERRIDE]
        derivations = [a for a in active if a.phase is Phase.DERIVATION]

        frame = self._source
        for action in (*overrides, *derivations):
            frame = self._apply_guarded(action, frame)
        return frame

    def _apply_guarded(self, action: BaseAction, frame: pl.DataFrame) -> pl.DataFrame:
        before = _key_multiset(frame, self._key)
        out = action.apply(frame, key_column=self._key)
        if not action.allow_identity_change:
            self._assert_identity(before, out, action)
        return out

    def _assert_identity(
        self, before: list | None, out: pl.DataFrame, action: BaseAction
    ) -> None:
        if self._key not in out.columns:
            raise IdentityGuardError(
                f"{action.label()} would remove the identity column "
                f"{self._key!r}; pass allow_identity_change=True to force"
            )
        after = _key_multiset(out, self._key)
        if after != before:
            raise IdentityGuardError(
                f"{action.label()} would change identity column {self._key!r} "
                f"values; pass allow_identity_change=True to force"
            )

    # -- derived metadata ---------------------------------------------------

    def units_sidecar(self) -> dict[str, str]:
        """Column -> unit, folded from the active actions (last write wins)."""
        sidecar: dict[str, str] = {}
        for action in self.actions:
            sidecar.update(action.units())
        return sidecar

    # -- persistence --------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialise the session (actions + cursor). The source frame is not
        stored — reload with the same ``read_table`` output."""
        return {
            "key_column": self._key,
            "cursor": self._cursor,
            "actions": [a.to_dict() for a in self._actions],
        }

    @classmethod
    def from_dict(cls, source: pl.DataFrame, d: dict[str, Any]) -> "Recipe":
        recipe = cls(source, key_column=d["key_column"])
        recipe._actions = [action_from_dict(a) for a in d["actions"]]
        recipe._cursor = d["cursor"]
        recipe.result()  # validate on load
        return recipe
