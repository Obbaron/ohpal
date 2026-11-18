"""Names for a build of AMPM Viewer, shared by ``app.spec`` (PyInstaller) and
``installer/build_installer.py`` (Inno Setup), so the two always agree.

- ``version()``: ``__version__`` from ``src/ampm_viewer/__init__.py``.
- ``arch()``: x64 or arm64, the architecture of the Python running this
  (PyInstaller builds for it, so an x64 Python on an Arm PC makes an x64 app).
- ``dist_name()``: ``ampm-viewer-v<version>-<arch>``, the build's folder in
  ``dist`` and the stem of its setup file (``...-setup.exe``).
- ``EXE_NAME``: the program inside the folder, ``AMPM Viewer(.exe)``. It
  carries no version, so shortcuts and taskbar pins survive an upgrade.

No imports beyond the standard library: PyInstaller runs the spec in the
build environment and the installer script may run outside it.
"""

from __future__ import annotations

import re
import sysconfig
from pathlib import Path

HERE = Path(__file__).resolve().parent          # apps/ampm_viewer
EXE_NAME = "AMPM Viewer"
APP_NAME = "AMPM Viewer"
PUBLISHER = "Oliver H. Page"


def version() -> str:
    init = (HERE / "src" / "ampm_viewer" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__\s*=\s*"([^"]+)"', init).group(1)


def version_numbers() -> tuple[int, int, int, int]:
    """The version as four numbers (Windows file and setup versions)."""
    nums = [int(n) for n in re.findall(r"\d+", version())[:4]]
    return tuple(nums + [0] * (4 - len(nums)))


def arch() -> str:
    plat = sysconfig.get_platform().lower()  # win-amd64, win-arm64, linux-aarch64, ...
    if plat.endswith(("arm64", "aarch64")):
        return "arm64"
    if plat.endswith(("amd64", "x86_64")):
        return "x64"
    if plat.endswith(("win32", "i686", "i386")):
        return "x86"
    return plat.rsplit("-", 1)[-1]


def dist_name() -> str:
    return f"ampm-viewer-v{version()}-{arch()}"
