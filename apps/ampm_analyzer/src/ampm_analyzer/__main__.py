# Lets `python -m ampm_analyzer` and console script share entry point.
# Overhaul in progress: the new PyQt6 shell replaces the legacy GUI. The old
# window still lives in main.py (its main() is importable as
# `ampm_analyzer.main:main`) and is the analysis logic the shell is wired to
# in a later pass.
# Absolute (not relative) import: PyInstaller runs this file as the top-level
# ``__main__`` script, which has no parent package, so ``from .shell …`` would
# fail with "attempted relative import with no known parent package". The
# absolute form resolves the bundled package and works equally for
# ``python -m ampm_analyzer`` and the ``ampm-analyzer`` console script.
from ampm_analyzer.shell.app import main

if __name__ == "__main__":
    main()
