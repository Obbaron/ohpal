# Lets `python -m ampm_analyzer` and console script share entry point.
# Overhaul in progress: the new PyQt6 shell replaces the legacy GUI. The old
# window still lives in main.py (its main() is importable as
# `ampm_analyzer.main:main`) and is the analysis logic the shell is wired to
# in a later pass.
from .shell.app import main

if __name__ == "__main__":
    main()
