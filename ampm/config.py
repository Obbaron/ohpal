"""
config.py - shared configuration for ampm analysis

Usage:
    from config import load_config
    config = load_config("path/to/build_directory")

    Or to auto-generate config.toml if it doesn't exist:
    from config import create_or_load_config
    config = create_or_load_config("path/to/build_directory")

    The build directory should contain a `config.toml` file.
    Paths in the TOML can be relative or absolute.
"""

import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ModuleNotFoundError:
        try:
            import tomli as tomllib
        except ModuleNotFoundError:
            sys.exit(
                "Python < 3.11 requires the 'tomli' package.\n"
                "Install: pip install tomli"
            )


def _resolve_path(path_str: str, base_dir: Path) -> str:
    path = Path(path_str)
    if path.is_absolute():
        return str(path)
    return str(base_dir / path)


def load_config(build_dir: str | Path) -> dict:
    """
    Load configuration from a build directory's config.toml

    Parameters
    ----------
    build_dir : str | Path
        Path to the build directory containing config.toml

    Returns
    -------
    dict with keys: SOURCE, STL, PARTS_CSV, LAYER_THICKNESS,
                    MASK_CACHE, MASK_KEEP_CACHE, CLUSTER_CACHE
    """
    build_dir = Path(build_dir).resolve()
    toml_path = build_dir / "config.toml"

    try:
        with open(toml_path, "rb") as file:
            _config = tomllib.load(file)
    except FileNotFoundError:
        sys.exit(f"ERROR: config.toml not found in {build_dir}\n")
    except tomllib.TOMLDecodeError as e:
        sys.exit(f"ERROR: {toml_path} has invalid syntax:\n{e}")

    try:
        source = _resolve_path(_config["paths"]["source"], build_dir)
        stl = _resolve_path(_config["paths"]["stl"], build_dir)
        parts_csv = _resolve_path(_config["paths"]["parts_csv"], build_dir)
        layer_thickness = _config["build"]["layer_thickness"]
    except KeyError as e:
        sys.exit(f"ERROR: Missing required key in {toml_path}: {e}")

    return {
        "SOURCE": source,
        "STL": stl,
        "PARTS_CSV": parts_csv,
        "LAYER_THICKNESS": layer_thickness,
        "MASK_CACHE": str(Path(source) / ".cache" / "fullplate_mask.pkl"),
        "MASK_KEEP_CACHE": str(Path(source) / ".cache" / "mask_keep.pq"),
        "CLUSTER_CACHE": str(Path(source) / ".cache" / "cluster_labels.pq"),
    }


def create_or_load_config(
    build_dir: str | Path,
    *,
    source: str | Path | None = None,
    stl: str | Path | None = None,
    parts_csv: str | Path | None = None,
) -> dict:
    """
    Load config.toml from the build directory, creating it first if absent.

    Parameters
    ----------
    build_dir : str | Path
        Path to the build directory.
    source : str, Path, or None
        Override for the packet data directory. Forwarded to
        ``setup_build.create_config`` if the TOML needs to be generated.
    stl : str, Path, or None
        Override for the STL file.
    parts_csv : str, Path, or None
        Override for the QuantAM parts CSV.

    Returns
    -------
    dict with keys: SOURCE, STL, PARTS_CSV, LAYER_THICKNESS,
                    MASK_CACHE, MASK_KEEP_CACHE, CLUSTER_CACHE
    """
    build_dir = Path(build_dir).resolve()
    toml_path = build_dir / "config.toml"

    if not toml_path.exists():
        from ampm.setup_build import create_config

        create_config(
            build_dir,
            source=source,
            stl=stl,
            parts_csv=parts_csv,
        )

    return load_config(build_dir)
