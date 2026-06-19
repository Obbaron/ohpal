# Makefile Guide

## What is a Makefile?

A Makefile is a simple automation script used by the make tool to define common project tasks as named commands.

Instead of remembering long or error-prone commands like:

python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
pytest

you can run:

make setup
make test

Each target in the Makefile represents a task (like setting up the environment, running tests, or building a binary).

This Makefile is designed to:

Standardize development workflows across Windows and Linux
Ensure Python version compatibility
Support both online installs and fully offline environments
Automate testing and packaging
Reduce onboarding friction for new developers
Cross-Platform Behavior

This Makefile automatically adapts based on the operating system:

Windows (OS = Windows_NT)
Shell: PowerShell
Python executable: python
Virtual environment Python: .venv\Scripts\python.exe
Wheel storage: wheels/windows
Linux/macOS
Shell: default Unix shell
Python executable: python3
Virtual environment Python: .venv/bin/python
Wheel storage: wheels/linux
Python Version Requirement

This project enforces a strict runtime requirement:

Python 3.11.x (64-bit only)

This is checked automatically before most operations via:

PYCHECK

It ensures compatibility with prebuilt wheels bundled in the project.

If the version or architecture is incorrect, the command will fail early with an error message.

Virtual Environment

All workflows assume a local virtual environment in:

.venv/

This is created and managed automatically by the Makefile.

Available Commands
make help

Shows a list of available commands.

make setup

Creates a fresh development environment and installs the project in editable mode (with development dependencies).

What it does:

Checks Python version (PYCHECK)
Deletes any existing .venv
Creates a new virtual environment
Upgrades pip

Installs the project:

pip install -e ".[dev]"

Use this for:

Initial setup
Resetting your dev environment
make offline

Creates a virtual environment using pre-downloaded wheels only (no internet access required).

What it does:

Checks Python version
Recreates .venv

Installs dependencies from:

wheels/<platform>/

without using PyPI

Use this for:

Air-gapped environments
Restricted networks
Reproducible installs
make wheels

Builds the offline dependency cache.

What it does:

Ensures correct Python version
Deletes existing wheel directory
Downloads all project dependencies as wheels:
Project dependencies (.[dev])
setuptools
wheel

Output location:

wheels/windows/   or   wheels/linux/

Use this when:

Preparing offline installation packages
Updating dependency bundles
make test

Runs the test suite using pytest:

.venv/.../python -m pytest

Use this for:

Running unit tests locally
CI validation (if configured externally)
make run

Runs the application entry point:

python app.py

Equivalent to launching the project directly in the virtual environment.

make build

Builds a standalone executable using PyInstaller:

python -m PyInstaller app.spec

Output typically goes into:

dist/
build/

Use this for:

Packaging the application for distribution
Creating standalone binaries
make clean

Removes temporary files and build artifacts.

On Linux/macOS:

rm -rf .pytest_cache build dist *.egg-info
find . -type d -name __pycache__ -exec rm -rf {} +

On Windows (PowerShell):

Remove-Item -Recurse -Force .pytest_cache, build, dist, *.egg-info
Get-ChildItem -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force

Cleans:

Test caches
Build outputs
Python bytecode caches
Packaging metadata

Use this when:

Resetting the repo state
Troubleshooting build issues
Typical Workflow
First-time setup:
make setup
Daily development:
make run
make test
Before release:
make clean
make wheels
make build
Summary

This Makefile is designed to make the project:

Easy to set up (make setup)
Reproducible (make offline, make wheels)
Testable (make test)
Packaged consistently (make build)
Cleanable across platforms (make clean)

It removes environment guesswork and standardizes developer workflows across Windows and Linux.