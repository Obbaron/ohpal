# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for AMPM Analyzer (build with `just build` / `just rebuild`).

Build on Windows (PowerShell): a Windows .exe must be built on Windows; a WSL
build produces a Linux binary. From the repo root:

    just setup            # once: sync the venv (uv sync --all-packages)
    just build            # runs: uv --directory apps/ampm_analyzer run pyinstaller app.spec

Output: apps/ampm_analyzer/dist/AMPM-Analyzer.exe, one self-contained file
(nothing beside it to ship). It unpacks itself to a temporary folder at each
start, so it starts a little slower than an unpacked app; a DBSCAN job the app
starts (the same .exe with --dbscan-job) reuses the running app's unpacked
copy. Paths here are relative to this spec's folder (apps/ampm_analyzer),
which is where `just build` runs it.
"""

import re
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

NAME = "AMPM-Analyzer"
ICON = "src/ampm_analyzer/assets/ampm.ico"

# -- version (one place: src/ampm_analyzer/__init__.py) ----------------------
_init = Path("src/ampm_analyzer/__init__.py").read_text(encoding="utf-8")
VERSION = re.search(r'__version__\s*=\s*"([^"]+)"', _init).group(1)
_nums = [int(n) for n in re.findall(r"\d+", VERSION)[:3]]
_nums += [0] * (4 - len(_nums))

# The Windows file properties (Details tab): name, version, description.
# (Written into PyInstaller's build folder, ``workpath``, not the source tree.)
_version_file = Path(workpath) / "version_info.txt"  # noqa: F821 (spec global)
_version_file.parent.mkdir(parents=True, exist_ok=True)
_version_file.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={tuple(_nums)}, prodvers={tuple(_nums)},
                    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1,
                    subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Oliver H. Page'),
      StringStruct('FileDescription', 'AMPM Analyzer'),
      StringStruct('FileVersion', '{VERSION}'),
      StringStruct('InternalName', '{NAME}'),
      StringStruct('LegalCopyright', 'All rights reserved'),
      StringStruct('OriginalFilename', '{NAME}.exe'),
      StringStruct('ProductName', 'AMPM Analyzer'),
      StringStruct('ProductVersion', '{VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""", encoding="utf-8")

# -- data files ---------------------------------------------------------
datas = []
# The app's icon, help articles, fonts and SVG icons, loaded at runtime from
# the package (Path(__file__)/assets), so they keep their package-relative
# location in the bundle.
datas += collect_data_files("ampm_analyzer", includes=["assets/**/*",
                                                        "shell/assets/**/*"])
# VisPy ships GLSL shaders, fonts and data it loads at runtime.
datas += collect_data_files("vispy")

# -- hidden imports -----------------------------------------------------
hiddenimports = []
# ohpal.* is a namespace package imported lazily inside functions, so
# PyInstaller's static scan misses most of it — pull every submodule in.
hiddenimports += collect_submodules("ohpal")
# VisPy resolves its GUI backend dynamically; name the PyQt6 one explicitly.
hiddenimports += ["vispy.app.backends._pyqt6"]
# QtSvg renders the icons; keep it even if the PyQt6 hook would add it.
hiddenimports += ["PyQt6.QtSvg"]

a = Analysis(
    ["src/ampm_analyzer/__main__.py"],
    pathex=[
        "src",
        "../../packages/ohpal_ampm/src",
        "../../packages/ohpal_core/src",
        "../../packages/ohpal_samples/src",
    ],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Trim weight: nothing in the app uses these (should one be installed in
    # the build environment anyway).
    excludes=["tkinter", "matplotlib", "plotly", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

# One file: the scripts, every library and data file go into the .exe itself
# (no COLLECT step, no _internal folder beside it).
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,  # unpack to the user's temp folder
    console=False,  # GUI app — no console window. Flip to True to see tracebacks.
    disable_windowed_traceback=False,
    icon=ICON,  # the .exe's own icon (Explorer, taskbar)
    version=str(_version_file),
)
