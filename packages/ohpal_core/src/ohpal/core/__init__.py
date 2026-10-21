"""``ohpal.core`` — shared contracts and build-file identity.

The lowest package in the workspace: it owns the machine build-file reader and
the canonical ``part_id`` key, so ``ohpal.samples`` and ``ohpal.ampm`` can both
depend on it without depending on each other.
"""

from __future__ import annotations

from ohpal.core.build import (
    BuildFileError,
    BuildParts,
    PartResolutionError,
)
from ohpal.core.identity import (
    PART_ID,
    DirectColumnResolver,
    IdentityError,
    NoApplicableResolver,
    PartIdentityResolver,
    SpatialBBoxResolver,
    default_resolvers,
    resolve_part_id,
)
from ohpal.core.parts import (
    BUILD_ID,
    MergeError,
    PartAttributeProvider,
    attribute_columns,
    merge,
    namespace_columns,
)

__all__ = [
    # build
    "BuildParts",
    "BuildFileError",
    "PartResolutionError",
    # identity
    "PART_ID",
    "PartIdentityResolver",
    "DirectColumnResolver",
    "SpatialBBoxResolver",
    "default_resolvers",
    "resolve_part_id",
    "IdentityError",
    "NoApplicableResolver",
    # parts contract + merge
    "BUILD_ID",
    "PartAttributeProvider",
    "namespace_columns",
    "attribute_columns",
    "merge",
    "MergeError",
]
