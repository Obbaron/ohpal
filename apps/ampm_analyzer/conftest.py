"""Registers the ``--build`` option for the app's tests (see tests/conftest.py).

It lives here, at the app's root, because pytest only takes command-line
options from conftest files it loads before reading the command line; this
one is always loaded when running from this folder (``just test-app``).
"""

from __future__ import annotations


def pytest_addoption(parser) -> None:
    parser.addoption(
        "--build", default=None,
        help="build folder for the GUI scenarios, as --build=PATH (or set AMPM_TEST_BUILD)")
