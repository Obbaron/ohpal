"""Fixtures for the app's tests: the build they run on.

The GUI scenarios need a real build folder (they were written against JR299:
10 layers, 20 parts, a parts CSV, an STL and a DHXML). It isn't in the repo:
point the tests at one on your machine, any of these ways:

    just test-app "C:\\builds\\JR299"
    pytest apps/ampm_analyzer/tests "--build=C:\\builds\\JR299"
    AMPM_TEST_BUILD=/path/to/JR299 pytest apps/ampm_analyzer/tests

(Write ``--build=PATH`` as one argument: pytest reads the command line before
it knows the option, and would take a separate PATH for a test path.)

Without one, the scenarios that need a build are skipped (with this hint).

Once per run, the build is copied (without its ``.cache`` or ``exports``) and
its DataStore built fresh, the way the app builds it with default settings:
the state a user is in after opening the build and building its DataStore.
Each scenario then gets its own copy of that, so your folder is never written
to and no scenario sees another's changes.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

ENV = "AMPM_TEST_BUILD"
_HINT = (f"needs a build folder: pass --build=PATH or set {ENV} "
         "(the scenarios were written against JR299)")


def _check_relative_paths(build: Path) -> None:
    """A copy is only self-contained if config.toml's paths are relative."""
    config = build / "config.toml"
    if not config.is_file():
        return
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10
        import tomli as tomllib
    paths = tomllib.loads(config.read_text(encoding="utf-8")).get("paths", {})
    absolute = [k for k, v in paths.items()
                if isinstance(v, str) and Path(v).is_absolute()]
    if absolute:
        pytest.fail(
            f"{config}: [paths] {', '.join(absolute)} absolute. The tests work "
            "on a copy of the build, which would still read (and write caches "
            "into) the original: make them relative to the build folder.")


@pytest.fixture(scope="session")
def source_build(request) -> Path:
    """The build folder the scenarios run on (never written to)."""
    path = request.config.getoption("--build") or os.environ.get(ENV)
    if not path:
        pytest.skip(_HINT)
    build = Path(path).expanduser().resolve()
    if not build.is_dir():
        pytest.skip(f"{build} is not a folder; {_HINT}")
    _check_relative_paths(build)
    return build


def _build_datastore(build: Path) -> None:
    """Convert every layer, as the app's Build DataStore does by default."""
    from ohpal.ampm import DataStore
    from ohpal.ampm.config import load_config
    from ohpal.ampm.setup_build import create_config

    if not (build / "config.toml").exists():
        create_config(build)
    config = load_config(build)
    thickness = float(config.get("LAYER_THICKNESS") or 0.03) or 0.03
    store = DataStore(Path(config["SOURCE"]), layer_thickness=thickness)
    store.build_cache(layers=list(store.layers), force=True, verbose=False)


@pytest.fixture(scope="session")
def prepared_build(source_build: Path, tmp_path_factory) -> Path:
    """The build with a fresh DataStore (built once per test run)."""
    dest = tmp_path_factory.mktemp("prepared") / source_build.name
    shutil.copytree(source_build, dest,
                    ignore=shutil.ignore_patterns(".cache", "exports"))
    _build_datastore(dest)
    return dest


@pytest.fixture
def build_copy(prepared_build: Path, tmp_path: Path) -> Path:
    """This scenario's own copy of the prepared build."""
    dest = tmp_path / prepared_build.name
    shutil.copytree(prepared_build, dest)
    return dest
