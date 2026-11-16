# Lets `python -m ampm_analyzer`, the `ampm-analyzer` script and the packaged
# app share one entry point.
# Absolute (not relative) import: PyInstaller runs this file as the top-level
# ``__main__`` script, which has no parent package, so ``from .shell …`` would
# fail with "attempted relative import with no known parent package". The
# absolute form resolves the bundled package and works equally for
# ``python -m ampm_analyzer`` and the ``ampm-analyzer`` console script.
from ampm_analyzer.shell.app import main

if __name__ == "__main__":
    main()
