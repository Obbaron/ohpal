"""Registers the ``--build`` option for the app's tests (see tests/conftest.py).

It lives here, at the app's root, because pytest only takes command-line
options from conftest files it loads before reading the command line; this
one is always loaded when running from this folder (``just test-app``).
"""

from __future__ import annotations

import os

# Scenarios at once with ``-n auto`` (pytest-xdist): one per CPU core, at
# most MAX_WORKERS, and no more than the memory allows. Each scenario is its
# own app process querying and drawing a build; the heaviest (plot_controls,
# a dozen plots open at once) peaks near 3 GB, so a worker is given that much.
MAX_WORKERS = 6
GB_PER_WORKER = 3


def _total_memory_gb() -> float | None:
    """The machine's memory in GB (None when it can't be told)."""
    try:
        if os.name == "nt":
            import ctypes

            class _Status(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            status = _Status()
            status.dwLength = ctypes.sizeof(_Status)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return None
            return status.ullTotalPhys / 2**30
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30
    except (AttributeError, OSError, ValueError):
        return None


def pytest_xdist_auto_num_workers(config) -> int:
    workers = min(MAX_WORKERS, os.cpu_count() or 1)
    memory = _total_memory_gb()
    if memory:
        workers = min(workers, int(memory // GB_PER_WORKER))
    return max(1, workers)


def pytest_addoption(parser) -> None:
    parser.addoption(
        "--build", default=None,
        help="build folder for the GUI scenarios, as --build=PATH (or set AMPM_TEST_BUILD)")
