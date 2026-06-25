"""
ampm_analyzer.views

Each .py file in this package that defines NAME, AXES, SETTINGS, and run()
is automatically discovered and made available to the app.

Beyond the built-in views, additional views are loaded at runtime from external
folders, so new plot types can be dropped in without rebuilding the app (this
works in the compiled .exe too, since these are read from disk, not the bundle).

External view folders, in increasing precedence (later overrides earlier on a
NAME collision):

    1. User data directory   (lowest)  - shared across all builds
         Windows : %APPDATA%/AMPM/views
         macOS   : ~/Library/Application Support/AMPM/views
         Linux   : $XDG_DATA_HOME/AMPM/views  (or ~/.local/share/AMPM/views)
    2. Per-build             <project_root>/views/
    3. AMPM_VIEWS_PATH       (highest) - os.pathsep-separated dirs; earlier
                                         entries take precedence (like PATH)

Any external view may override a built-in of the same NAME.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from pathlib import Path
from typing import Callable

_KNOWN_VIEWS = [
    "bar",
    "contour",
    "cov_summary",
    "k_distance",
    "kde",
    "single_layer",
    "layer_viewer",
    "scatter_2d",
    "scatter_3d",
]

_REQUIRED = ("NAME", "AXES", "SETTINGS", "run")


def discover(
    project_root: str | Path | None = None,
    *,
    log: Callable[[str], None] | None = None,
) -> dict[str, object]:
    """
    Discover view modules and return ``{NAME: module}``.

    Parameters
    ----------
    project_root
        If given, the build's ``<project_root>/views/`` folder is also scanned.
    log
        Optional callback for diagnostics (skipped files, overrides, import
        errors). Defaults to silent.

    A valid view module must define:
        NAME: str           # display name for the GUI
        DESCRIPTION: str    # tooltip / help text (optional)
        AXES: dict          # column picker definitions
        SETTINGS: dict      # extra widget definitions
        run(df, config, axes, settings): None
    """

    def _emit(msg: str) -> None:
        if log is not None:
            log(msg)

    views: dict[str, object] = {}

    _discover_builtin(views, _emit)

    for label, folder in _external_view_dirs(project_root):
        _discover_external(views, folder, label, _emit)

    return views


def _discover_builtin(views: dict[str, object], emit: Callable[[str], None]) -> None:
    if getattr(sys, "frozen", False):
        stems = _KNOWN_VIEWS
    else:
        package_dir = Path(__file__).parent
        stems = [
            path.stem
            for path in sorted(package_dir.glob("*.py"))
            if not path.name.startswith("_")
        ]

    for stem in stems:
        try:
            module = importlib.import_module(f"{__package__}.{stem}")
        except Exception as e:
            emit(f"[views] failed to import built-in '{stem}': {e}")
            continue

        if _is_valid_view(module):
            views[getattr(module, "NAME")] = module


def _discover_external(
    views: dict[str, object],
    folder: Path,
    label: str,
    emit: Callable[[str], None],
) -> None:
    try:
        if not folder.is_dir():
            return
    except OSError:
        return

    for py_file in sorted(folder.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        try:
            module = _load_view_from_path(py_file)
        except Exception as e:
            emit(f"[views] skipped {py_file} ({label}): import failed: {e}")
            continue
        if not _is_valid_view(module):
            emit(
                f"[views] skipped {py_file.name} ({label}): "
                f"missing one of {', '.join(_REQUIRED)}"
            )
            continue
        name = getattr(module, "NAME")
        if name in views:
            emit(f"[views] '{name}' from {label} overrides an earlier view")
        views[name] = module


def _load_view_from_path(py_file: Path) -> object:
    """Load a view module directly from a filesystem path."""
    mod_name = f"ampm_view_ext_{abs(hash(str(py_file)))}_{py_file.stem}"
    spec = importlib.util.spec_from_file_location(mod_name, py_file)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not create import spec for {py_file}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module  # so dataclasses / inspect / pickling work
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(mod_name, None)
        raise
    return module


def _is_valid_view(module: object) -> bool:
    return all(hasattr(module, attr) for attr in _REQUIRED)


def _external_view_dirs(
    project_root: str | Path | None,
) -> list[tuple[str, Path]]:
    """External view dirs, lowest -> highest priority."""
    dirs: list[tuple[str, Path]] = []

    dirs.append(("user data dir", _user_views_dir()))

    if project_root:
        dirs.append(("build", Path(project_root) / "views"))

    env = os.environ.get("AMPM_VIEWS_PATH", "")
    if env.strip():
        paths = [p for p in env.split(os.pathsep) if p.strip()]
        for p in reversed(paths):
            dirs.append(("AMPM_VIEWS_PATH", Path(p)))

    return dirs


def _user_views_dir() -> Path:
    """Cross-platform per-user views directory."""
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "AMPM" / "views"


def ensure_user_views_dir() -> Path:
    """Return the per-user views directory, creating it if it doesn't exist."""
    folder = _user_views_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return folder
