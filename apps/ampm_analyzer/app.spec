# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for AMPM Analyzer (build with `just build` / `just rebuild`).

Build on Windows (PowerShell) — a Windows .exe must be built on Windows; a WSL
build produces a Linux binary. From the repo root:

    just setup            # once: sync the venv (uv sync --all-packages)
    just build            # runs: uv --directory apps/ampm_analyzer run pyinstaller app.spec

Output: apps/ampm_analyzer/dist/AMPM-Analyzer/AMPM-Analyzer.exe (a one-folder
app — ship the whole AMPM-Analyzer folder). Paths here are relative to this
spec's folder (apps/ampm_analyzer), which is where `just build` runs it.
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# -- data files ---------------------------------------------------------
datas = []
# The app's bundled SVG icons, loaded at runtime via Path(__file__)/assets/icons
# — so they must keep their package-relative location in the bundle.
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
    # Trim weight: the app uses neither.
    excludes=["tkinter", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AMPM-Analyzer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI app — no console window. Flip to True to see tracebacks.
    disable_windowed_traceback=False,
    icon=None,      # set to "assets/app.ico" once you have one
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="AMPM-Analyzer",
)
