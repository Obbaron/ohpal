"""AMPM Analyzer: the desktop app over the ``ohpal.ampm`` pipeline."""

# The app's version: the one place to change it (pyproject.toml reads it from
# here). Shown in Help and written into crash reports.
__version__ = "2.0.0"


def main() -> None:
    """Launch the app (the ``ampm-analyzer`` script and ``python -m``)."""
    from .shell.app import main as _main

    _main()


__all__ = ["__version__", "main"]
